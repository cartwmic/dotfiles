import test from "node:test";
import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { reconcileOverview } from "../src/coordinator.mjs";
import { renderOverview } from "../src/pane.mjs";

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

test("startup and reconcile never create or delete views and preserve legacy owner tabs", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "herdr-overview-coordinator-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const stateDir = path.join(root, "state");
  const dataRoot = path.join(root, "session-recap");
  const configPath = path.join(root, "config.toml");
  await writeFile(configPath, '[theme]\nname = "nord"\nauto_switch = false\n');
  let hasOverview = true;
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
    async readPane(paneId) { return output; },
    async processInfo(paneId) {
      if (paneId === "ws-a:p-overview") return overviewProcessRunning
        ? { foreground_processes: [{ argv0: "node", argv: ["index.mjs", "overview"], cmdline: "node index.mjs overview" }] }
        : { foreground_processes: [{ name: "sh", argv0: "sh", argv: ["/bin/sh"] }] };
      return { foreground_processes: [{ name: "node" }] };
    },
  };

  const first = await reconcileOverview({ api, stateDir, dataRoot, configPath });
  assert.equal(opens, 0);
  assert.equal(first.overviewPaneId, undefined);
  assert.deepEqual(Object.keys(first.model.panes), ["ws-a:p1", "ws-a:p-overview"]);
  assert.equal(first.model.panes["ws-a:p1"].agent.status, "unknown");
  assert.equal(first.model.panes["ws-a:p1"].preview, "initial output");
  assert.equal(first.theme.name, "nord");

  const second = await reconcileOverview({ api, stateDir, dataRoot, configPath });
  assert.equal(opens, 0);
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
  assert.equal(persisted.overviewPaneId, undefined);

  overviewProcessRunning = false;
  const restarted = await reconcileOverview({ api, stateDir, dataRoot, configPath });
  assert.equal(closes, 0, "owner legacy tab is never closed");
  assert.equal(opens, 0);
  assert.ok(restarted.model.panes['ws-a:p-overview']);
});

test("reconciliation and pane detail retain a Pi prompt after Herdr rekeys its pane ID", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "herdr-overview-moved-prompt-path-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const stateDir = path.join(root, "state");
  const dataRoot = path.join(root, "session-recap");
  const configPath = path.join(root, "config.toml");
  const sessionId = "pi-session-moved";
  const currentPaneId = "w2:p3";
  const terminalId = "terminal-stable-4";
  await writeFile(configPath, '[theme]\nname = "nord"\nauto_switch = false\n');
  await mkdir(path.join(dataRoot, "prompts"), { recursive: true });
  await writeFile(path.join(dataRoot, "prompts", `${encodeURIComponent(sessionId)}.json`), JSON.stringify({
    schema_version: 1,
    session_id: sessionId,
    pane_id: "w1:p4",
    text: "Continue after the pane move",
    working: true,
    captured_at: "2026-09-27T13:00:00Z",
  }));
  await mkdir(stateDir, { recursive: true });
  await writeFile(path.join(stateDir, "overview.json"), JSON.stringify({
    recapCoordinator: { piTerminalIdsBySessionId: { [sessionId]: terminalId } },
  }));

  const snapshot = {
    protocol: 22,
    version: "0.9.1",
    focused_workspace_id: "w2",
    focused_tab_id: "w2:t1",
    focused_pane_id: currentPaneId,
    workspaces: [{ workspace_id: "w2", number: 2, label: "Current", focused: true, active_tab_id: "w2:t1", agent_status: "working" }],
    tabs: [{ tab_id: "w2:t1", workspace_id: "w2", number: 1, label: "Main", focused: true, pane_count: 1, agent_status: "working" }],
    panes: [{
      pane_id: currentPaneId,
      workspace_id: "w2",
      tab_id: "w2:t1",
      terminal_id: terminalId,
      focused: true,
      label: "Pi task",
      agent: "pi",
      agent_status: "working",
    }],
    agents: [{ pane_id: currentPaneId, agent: "pi" }],
    layouts: [],
  };
  assert.equal(Object.hasOwn(snapshot.panes[0], "agent_session"), false);
  assert.equal(Object.hasOwn(snapshot.agents[0], "agent_session"), false);
  const api = {
    async snapshot() { return snapshot; },
    async readPane(paneId) { assert.equal(paneId, currentPaneId); return "output after move"; },
    async processInfo() { return null; },
  };

  const state = await reconcileOverview({ api, stateDir, dataRoot, configPath, openPane: false });
  assert.equal(state.model.panes[currentPaneId].prompt.pane_id, "w1:p4");
  assert.equal(state.model.panes[currentPaneId].agent.session, null);
  const detail = renderOverview({
    ...state,
    journey: { level: "pane", workspaceId: "w2", tabId: "w2:t1", paneId: currentPaneId, detailScroll: 0 },
  }, 60, 24);
  assert.doesNotMatch(detail, /output after move/);
  assert.match(detail, /Supplied prompt/);
  assert.match(detail, /Continue after the pane move/);
});

test("an automatically owned Pi pane survives pane.created before pane.moved", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "herdr-overview-moved-automatic-name-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const stateDir = path.join(root, "state");
  const dataRoot = path.join(root, "session-recap");
  const configPath = path.join(root, "config.toml");
  await mkdir(stateDir);
  await mkdir(path.join(dataRoot, "records", "2026-09-27"), { recursive: true });
  await writeFile(configPath, '[theme]\nname = "nord"\nauto_switch = false\n');
  const recap = {
    schema_version: 1, record_id: "new-task", source_kind: "pi-session", source_id: "session-one",
    kind: "single", pane_id: "w2:p1", workspace_id: "w2", status: "published",
    summary: "A distinct second task is now complete.",
    created_at: "2026-09-27T10:00:00Z", published_at: "2026-09-27T10:00:01Z",
  };
  await writeFile(path.join(dataRoot, "records", "2026-09-27", "new-task.json"), JSON.stringify(recap));
  await writeFile(path.join(dataRoot, "latest.json"), JSON.stringify({ sources: [{
    source_kind: "pi-session", source_id: "session-one", latest_success_id: "new-task", last_attempt_id: "new-task",
  }] }));
  await writeFile(path.join(stateDir, "overview.json"), JSON.stringify({
    model: { panes: { "w1:p1": { terminalId: "stable-terminal", preview: "prior output" } } },
    displayNameOwnership: { "pane:w1:p1": {
      mode: "automatic", lastWrittenLabel: "Old automatic task", observedLabel: "Old automatic task", defaultLabel: null,
    } },
  }));
  let label = "Old automatic task";
  let paneId = "w2:p1";
  const renames = [];
  const api = {
    async snapshot() {
      return {
        protocol: 22, version: "0.9.1", focused_workspace_id: "w2", focused_tab_id: "w2:t1", focused_pane_id: paneId,
        workspaces: [{ workspace_id: "w2", number: 2, label: "Bravo", focused: true, active_tab_id: "w2:t1" }],
        tabs: [{ tab_id: "w2:t1", workspace_id: "w2", number: 1, label: "1", focused: true }],
        panes: [{ pane_id: paneId, workspace_id: "w2", tab_id: "w2:t1", terminal_id: "stable-terminal",
          label, terminal_title_stripped: "π - Stable moved task - /repo", agent: "pi", focused: true, agent_status: "done" }],
        agents: [{ pane_id: paneId, agent: "pi" }], layouts: [],
      };
    },
    async readPane() { return "second task output"; },
    async processInfo() { return null; },
    async renamePane(id, next) { renames.push([id, next]); label = next; },
    async renameTab() {},
  };
  const state = await reconcileOverview({ api, stateDir, dataRoot, configPath, openPane: false,
    event: { event: "pane.created", data: { pane: { pane_id: "w2:p1" } } },
  });
  assert.equal(state.displayNameOwnership["pane:w2:p1"].mode, "automatic");
  assert.equal(state.displayNameOwnership["pane:w1:p1"], undefined);
  assert.deepEqual(renames, [["w2:p1", "Stable moved task"]]);
  assert.equal(state.model.panes["w2:p1"].label, "Stable moved task");
  assert.equal(state.model.panes["w2:p1"].recap.latest.summary, recap.summary);
  const lateMove = await reconcileOverview({ api, stateDir, dataRoot, configPath, openPane: false,
    event: { event: "pane.moved", data: { previous_pane_id: "w1:p1", pane: { pane_id: "w2:p1" } } },
  });
  assert.equal(lateMove.displayNameOwnership["pane:w2:p1"].mode, "automatic");
  assert.deepEqual(renames, [["w2:p1", "Stable moved task"]]);

  label = "Owner takes over the moved pane";
  const manual = await reconcileOverview({ api, stateDir, dataRoot, configPath, openPane: false,
    event: { event: "pane.updated", data: { pane_id: paneId } },
  });
  assert.equal(manual.displayNameOwnership["pane:w2:p1"].mode, "manual");
  paneId = "w2:p2";
  const movedAgain = await reconcileOverview({ api, stateDir, dataRoot, configPath, openPane: false,
    event: { event: "pane.created", data: { pane: { pane_id: paneId } } },
  });
  assert.equal(movedAgain.displayNameOwnership["pane:w2:p2"].mode, "manual");
  assert.equal(movedAgain.model.panes[paneId].label, label);
  assert.deepEqual(renames, [["w2:p1", "Stable moved task"]]);
});

test("empty-server startup and workspace events remain view-free", async (t) => {
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
  assert.equal(startup.overviewPaneId, undefined);
  assert.deepEqual(startup.model.workspaceOrder, []);

  hasWorkspace = true;
  const created = await reconcileOverview({
    api, stateDir, configPath, openPane: true,
    event: { event: "workspace.created", data: { type: "workspace_created" } },
  });
  assert.equal(opens, 0);
  assert.equal(created.overviewPaneId, undefined);
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

test("owner renames after policy evaluation survive each queued automatic write", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "herdr-overview-queued-name-race-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const stateDir = path.join(root, "state");
  const configPath = path.join(root, "config.toml");
  await writeFile(configPath, '[theme]\nname = "nord"\nauto_switch = false\n');
  const current = makeSnapshot();
  current.tabs[0].label = "1";
  let snapshots = 0;
  const renames = [];
  const api = {
    async snapshot() {
      snapshots += 1;
      const observed = structuredClone(current);
      if (snapshots === 2) {
        // The earlier policy refresh has captured defaults; the owner edits
        // land before its queued pane/tab renames reach Herdr.
        current.panes[0].label = "Owner Proof Alpha shell";
        current.tabs[0].label = "Owner Proof Alpha tab";
      }
      return observed;
    },
    async readPane() { return "recent output"; },
    async processInfo() { return { foreground_processes: [{ name: "bash" }] }; },
    async renamePane(id, label) { renames.push(["pane", id, label]); current.panes[0].label = label; },
    async renameTab(id, label) { renames.push(["tab", id, label]); current.tabs[0].label = label; },
  };

  const state = await reconcileOverview({ api, stateDir, configPath, openPane: false });
  assert.deepEqual(renames, []);
  assert.equal(snapshots, 4, "each queued pane/tab write got a final native snapshot");
  assert.equal(state.model.panes["ws-a:p1"].label, "Owner Proof Alpha shell");
  assert.equal(state.model.tabs["ws-a:t1"].label, "Owner Proof Alpha tab");
  assert.equal(state.displayNameOwnership["pane:ws-a:p1"].mode, "manual");
  assert.equal(state.displayNameOwnership["pane:ws-a:p1"].observedLabel, "Owner Proof Alpha shell");
  assert.equal(state.displayNameOwnership["tab:ws-a:t1"].mode, "manual");
  assert.equal(state.displayNameOwnership["tab:ws-a:t1"].observedLabel, "Owner Proof Alpha tab");
});
