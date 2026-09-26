import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { reconcileOverview } from "../src/coordinator.mjs";

function makeSnapshot(withOverview = false) {
  const panes = [{
    pane_id: "ws-a:p1", workspace_id: "ws-a", tab_id: "ws-a:t1", terminal_id: "term1",
    focused: true, agent_status: "unknown", revision: 1, cwd: "/repo", label: null,
  }];
  const tabs = [{ tab_id: "ws-a:t1", workspace_id: "ws-a", number: 1, label: "Main", focused: true, pane_count: 1, agent_status: "unknown" }];
  if (withOverview) {
    tabs.push({ tab_id: "ws-a:t-overview", workspace_id: "ws-a", number: 2, label: "Herdr Overview", focused: false, pane_count: 1, agent_status: "unknown" });
    panes.push({ pane_id: "ws-a:p-overview", workspace_id: "ws-a", tab_id: "ws-a:t-overview", terminal_id: "overview-term", focused: false, agent_status: "unknown", revision: 2, label: "Herdr Overview" });
  }
  return {
    protocol: 22, version: "0.9.1", focused_workspace_id: "ws-a", focused_tab_id: "ws-a:t1", focused_pane_id: "ws-a:p1",
    workspaces: [{ workspace_id: "ws-a", number: 1, label: "API", focused: true, pane_count: panes.length, tab_count: tabs.length, active_tab_id: "ws-a:t1", agent_status: "unknown" }],
    tabs, panes, agents: [], layouts: [],
  };
}

test("startup and reconcile share an idempotent initializer, exclude its own pane, and refresh invalidated output", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "herdr-overview-coordinator-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const stateDir = path.join(root, "state");
  const dataRoot = path.join(root, "session-recap");
  const configPath = path.join(root, "config.toml");
  await writeFile(configPath, '[theme]\nname = "nord"\nauto_switch = false\n');
  let hasOverview = false;
  let overviewProcessRunning = true;
  let opens = 0;
  let closes = 0;
  let output = "initial output";
  const api = {
    async snapshot() { return makeSnapshot(hasOverview); },
    async openOverviewPane(options) {
      opens += 1;
      assert.deepEqual(options, { placement: "tab", focus: false });
      hasOverview = true;
      return { plugin_pane: { pane: { pane_id: "ws-a:p-overview", tab_id: "ws-a:t-overview" } } };
    },
    async renameTab() {},
    async closePane(paneId) { assert.equal(paneId, "ws-a:p-overview"); closes += 1; hasOverview = false; },
    async readPane(paneId) { assert.equal(paneId, "ws-a:p1"); return output; },
    async processInfo(paneId) {
      if (paneId === "ws-a:p-overview") return overviewProcessRunning
        ? { foreground_processes: [{ argv0: "node", argv: ["index.mjs", "overview"], cmdline: "node index.mjs overview" }] }
        : { foreground_processes: [{ name: "sh", argv0: "sh", argv: ["/bin/sh"] }] };
      return { foreground_processes: [{ name: "node" }] };
    },
  };

  const first = await reconcileOverview({ api, stateDir, dataRoot, configPath });
  assert.equal(opens, 1);
  assert.equal(first.overviewPaneId, "ws-a:p-overview");
  assert.deepEqual(Object.keys(first.model.panes), ["ws-a:p1"]);
  assert.equal(first.model.panes["ws-a:p1"].agent.status, "unknown");
  assert.equal(first.model.panes["ws-a:p1"].preview, "initial output");
  assert.equal(first.theme.name, "nord");

  const second = await reconcileOverview({ api, stateDir, dataRoot, configPath });
  assert.equal(opens, 1);
  assert.equal(second.model.panes["ws-a:p1"].processInfo.foreground_processes[0].name, "node");

  output = "changed output";
  const third = await reconcileOverview({
    api, stateDir, dataRoot, configPath, openPane: false,
    event: { event: "pane.output_changed", data: { type: "pane_output_changed", pane_id: "ws-a:p1" } },
  });
  assert.equal(third.model.panes["ws-a:p1"].preview, "changed output");
  assert.equal(third.model.selection.paneId, "ws-a:p1");
  const persisted = JSON.parse(await readFile(path.join(stateDir, "overview.json"), "utf8"));
  assert.equal(persisted.schema_version, 1);
  assert.equal(persisted.overviewPaneId, "ws-a:p-overview");

  overviewProcessRunning = false;
  const restarted = await reconcileOverview({ api, stateDir, dataRoot, configPath });
  assert.equal(closes, 1, "only the stale plugin-owned shell pane is closed");
  assert.equal(opens, 2, "a stopped plugin pane is reopened on server startup");
  assert.equal(restarted.overviewPaneId, "ws-a:p-overview");
});

test("empty-server startup waits for the first native workspace before opening the pane", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "herdr-overview-empty-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const stateDir = path.join(root, "state");
  const configPath = path.join(root, "config.toml");
  await writeFile(configPath, '[theme]\nname = "nord"\nauto_switch = false\n');
  let hasWorkspace = false;
  let hasOverview = false;
  let opens = 0;
  const api = {
    async snapshot() {
      return hasWorkspace ? makeSnapshot(hasOverview) : { protocol: 22, version: "0.9.1", workspaces: [], tabs: [], panes: [], agents: [], layouts: [] };
    },
    async openOverviewPane() {
      opens += 1;
      hasOverview = true;
      return { plugin_pane: { pane: { pane_id: "ws-a:p-overview" } } };
    },
    async readPane() { return ""; },
    async processInfo() { return null; },
  };

  const startup = await reconcileOverview({ api, stateDir, configPath, openPane: true });
  assert.equal(opens, 0);
  assert.equal(startup.overviewPaneId, null);
  assert.deepEqual(startup.model.workspaceOrder, []);

  hasWorkspace = true;
  const created = await reconcileOverview({
    api, stateDir, configPath, openPane: true,
    event: { event: "workspace.created", data: { type: "workspace_created" } },
  });
  assert.equal(opens, 1);
  assert.equal(created.overviewPaneId, "ws-a:p-overview");
  assert.deepEqual(Object.keys(created.model.panes), ["ws-a:p1"]);
});

test("a manual pane and tab rename during reconciliation are not overwritten", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "herdr-overview-name-race-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const stateDir = path.join(root, "state");
  const configPath = path.join(root, "config.toml");
  await writeFile(configPath, '[theme]\nname = "nord"\nauto_switch = false\n');
  let paneLabel = null;
  let tabLabel = "1";
  const renames = [];
  const api = {
    async snapshot() {
      const snapshot = makeSnapshot();
      snapshot.panes[0].label = paneLabel;
      snapshot.tabs[0].label = tabLabel;
      return snapshot;
    },
    async readPane() {
      paneLabel = "Owner pane label";
      tabLabel = "Owner tab label";
      return "recent output";
    },
    async processInfo() { return { foreground_processes: [{ name: "bash" }] }; },
    async renamePane(id, label) { renames.push(["pane", id, label]); paneLabel = label; },
    async renameTab(id, label) { renames.push(["tab", id, label]); tabLabel = label; },
  };

  const state = await reconcileOverview({ api, stateDir, configPath, openPane: false });
  assert.deepEqual(renames, []);
  assert.equal(paneLabel, "Owner pane label");
  assert.equal(tabLabel, "Owner tab label");
  assert.equal(state.displayNameOwnership["pane:ws-a:p1"].mode, "manual");
  assert.equal(state.displayNameOwnership["tab:ws-a:t1"].mode, "manual");
});
