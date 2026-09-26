import test from "node:test";
import assert from "node:assert/strict";
import net from "node:net";
import { spawn } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { reconcileOverview } from "../src/coordinator.mjs";
import { displayNameResetFromContext, evaluateDisplayNamePolicy, recordDisplayNameWrite } from "../src/display-name-policy.mjs";

function snapshot({ paneLabels = [null], tabLabel = "1", agents = [], panes = null, tabs = null } = {}) {
  const paneRows = panes ?? paneLabels.map((label, index) => ({
    pane_id: `ws-a:p${index + 1}`,
    workspace_id: "ws-a",
    tab_id: "ws-a:t1",
    terminal_id: `term-${index + 1}`,
    label,
    cwd: "/repo/app",
    focused: index === 0,
    agent_status: "working",
    revision: index + 1,
  }));
  return {
    protocol: 22,
    version: "0.9.1",
    focused_workspace_id: "ws-a",
    focused_tab_id: "ws-a:t1",
    focused_pane_id: paneRows[0]?.pane_id ?? null,
    workspaces: [{ workspace_id: "ws-a", number: 1, label: "Do not rename", focused: true, active_tab_id: "ws-a:t1", agent_status: "working" }],
    tabs: tabs ?? [{ tab_id: "ws-a:t1", workspace_id: "ws-a", number: 1, label: tabLabel, focused: true, pane_count: paneRows.length, agent_status: "working" }],
    panes: paneRows,
    agents,
  };
}

function publishedRecap(paneId, summary, extra = {}) {
  return {
    latest: {
      status: "published",
      source_kind: "pi-session",
      pane_id: paneId,
      workspace_id: "ws-a",
      summary,
      ...extra,
    },
    lastAttempt: null,
  };
}

test("unlabelled panes and Herdr's positional numeric tab defaults enter automatic mode", () => {
  const current = snapshot({
    agents: [{ pane_id: "ws-a:p1", agent: "claude", display_agent: "Claude" }],
  });
  current.panes[0].title = null;
  const result = evaluateDisplayNamePolicy(current, {
    processByPaneId: { "ws-a:p1": { foreground_processes: [{ name: "zsh" }] } },
  });

  assert.deepEqual(result.rename, [
    { kind: "pane", id: "ws-a:p1", label: "Claude · app" },
    { kind: "tab", id: "ws-a:t1", label: "Claude · app" },
  ]);
  assert.equal(result.ownership["pane:ws-a:p1"].mode, "automatic");
  assert.equal(result.ownership["tab:ws-a:t1"].mode, "automatic");
  assert.equal(current.workspaces[0].label, "Do not rename");
  assert.equal(current.panes[0].agent_session, undefined);
});

test("a manual-looking initial pane or tab label is preserved", () => {
  const current = snapshot({ paneLabels: ["Owner pane"], tabLabel: "Main" });
  const result = evaluateDisplayNamePolicy(current, {
    processByPaneId: { "ws-a:p1": { foreground_processes: [{ name: "node" }] } },
  });

  assert.deepEqual(result.rename, []);
  assert.equal(result.ownership["pane:ws-a:p1"].mode, "manual");
  assert.equal(result.ownership["tab:ws-a:t1"].mode, "manual");
  assert.equal(result.snapshot.panes[0].label, "Owner pane");
  assert.equal(result.snapshot.tabs[0].label, "Main");
  assert.equal(result.ownership["workspace:ws-a"], undefined);
});

test("a positional default stays automatic when Herdr renumbers a tab", () => {
  const piSession = { source: "herdr:pi", agent: "pi", kind: "id", value: "pi-2" };
  const secondTab = { tab_id: "ws-a:t2", workspace_id: "ws-a", number: 2, label: "2", focused: true, pane_count: 1 };
  const current = snapshot({
    agents: [{ pane_id: "ws-a:p2", agent: "pi", agent_session: piSession }],
    panes: [{ pane_id: "ws-a:p2", workspace_id: "ws-a", tab_id: "ws-a:t2", label: null, agent: "pi", agent_session: piSession }],
    tabs: [
      { tab_id: "ws-a:t1", workspace_id: "ws-a", number: 1, label: "1", pane_count: 0 },
      secondTab,
    ],
  });
  const before = evaluateDisplayNamePolicy(current);
  const after = evaluateDisplayNamePolicy({ ...before.snapshot, tabs: [{ ...secondTab, label: "1" }] }, {
    ownership: before.ownership,
  });

  assert.equal(before.ownership["tab:ws-a:t2"].mode, "automatic");
  assert.equal(after.ownership["tab:ws-a:t2"].mode, "automatic");
  assert.deepEqual(after.rename, []);
});

test("a label changed by its owner after an automatic write becomes manual", () => {
  const first = evaluateDisplayNamePolicy(snapshot(), {
    processByPaneId: { "ws-a:p1": { foreground_processes: [{ name: "node" }] } },
  });
  for (const update of first.rename) recordDisplayNameWrite(first, update);
  const renamedByOwner = first.snapshot;
  renamedByOwner.panes[0].label = "Pinned by owner";

  const next = evaluateDisplayNamePolicy(renamedByOwner, {
    processByPaneId: { "ws-a:p1": { foreground_processes: [{ name: "node" }] } },
    ownership: first.ownership,
  });
  assert.equal(next.rename.some((entry) => entry.kind === "pane"), false);
  assert.equal(next.ownership["pane:ws-a:p1"].mode, "manual");
  assert.equal(next.ownership["pane:ws-a:p1"].observedLabel, "Pinned by owner");
  assert.equal(next.snapshot.panes[0].label, "Pinned by owner");
});

test("an explicit per-ID reset returns a manual pane or tab to automatic naming", () => {
  const current = snapshot({ paneLabels: ["Owner pane"], tabLabel: "Owner tab" });
  const manualOwnership = {
    "pane:ws-a:p1": { mode: "manual", observedLabel: "Owner pane", lastWrittenLabel: null },
    "tab:ws-a:t1": { mode: "manual", observedLabel: "Owner tab", lastWrittenLabel: null },
  };
  const paneReset = evaluateDisplayNamePolicy(current, {
    ownership: manualOwnership,
    processByPaneId: { "ws-a:p1": { foreground_processes: [{ name: "node" }] } },
    resetName: { kind: "pane", id: "ws-a:p1" },
  });
  assert.deepEqual(paneReset.rename, [{ kind: "pane", id: "ws-a:p1", label: "node · app" }]);
  assert.equal(paneReset.ownership["pane:ws-a:p1"].mode, "automatic");
  assert.equal(paneReset.ownership["tab:ws-a:t1"].mode, "manual");
  const tabReset = evaluateDisplayNamePolicy(current, {
    ownership: manualOwnership,
    processByPaneId: { "ws-a:p1": { foreground_processes: [{ name: "node" }] } },
    resetName: { kind: "tab", id: "ws-a:t1" },
  });
  assert.deepEqual(tabReset.rename, [{ kind: "tab", id: "ws-a:t1", label: "node · app" }]);
  assert.equal(tabReset.ownership["pane:ws-a:p1"].mode, "manual");
  assert.equal(tabReset.ownership["tab:ws-a:t1"].mode, "automatic");
  assert.deepEqual(displayNameResetFromContext({ tab_id: "ws-a:t1" }, "tab"), {
    kind: "tab", id: "ws-a:t1",
  });
  assert.deepEqual(displayNameResetFromContext({ focused_pane_id: "ws-a:p1", tab_id: "ws-a:t1" }, "pane"), {
    kind: "pane", id: "ws-a:p1",
  });
  assert.throws(() => evaluateDisplayNamePolicy(current, { resetName: { kind: "workspace", id: "ws-a" } }), /pane or tab/);
  assert.throws(() => displayNameResetFromContext({}), /selected pane or tab ID/);
});

test("Pi pane labels require a successful in-workspace published recap, never the live prompt", () => {
  const session = { source: "herdr:pi", agent: "pi", kind: "id", value: "pi-1" };
  const current = snapshot({
    agents: [{ pane_id: "ws-a:p1", agent: "pi", display_agent: "Pi", agent_session: session }],
  });
  current.panes[0].agent = "pi";
  current.panes[0].agent_session = session;
  const processByPaneId = { "ws-a:p1": { foreground_processes: [{ name: "pi" }] } };
  const run = (recap) => evaluateDisplayNamePolicy(current, {
    processByPaneId,
    supplied: {
      promptsBySessionId: { "pi-1": { text: "LIVE PROMPT MUST NOT BECOME THE NAME" } },
      piRecapsBySessionId: recap ? { "pi-1": recap } : {},
    },
  });

  assert.equal(run(null).rename.some((entry) => entry.kind === "pane"), false);
  assert.equal(run({ latest: { ...publishedRecap("ws-a:p1", "Ignored failed record").latest, status: "failed" } }).rename.some((entry) => entry.kind === "pane"), false);
  assert.equal(run(publishedRecap("ws-a:p1", "Published outside Herdr", { workspace_id: null })).rename.some((entry) => entry.kind === "pane"), false);
  const published = run(publishedRecap("ws-a:p1", "Published migration recap"));
  assert.deepEqual(published.rename, [
    { kind: "pane", id: "ws-a:p1", label: "Published migration recap" },
    { kind: "tab", id: "ws-a:t1", label: "Published migration recap" },
  ]);
  assert.equal(published.snapshot.panes[0].agent_session.value, "pi-1");
});

test("overview.reconcile names Pi panes only from successful in-workspace recap records", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "herdr-pi-names-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const stateDir = path.join(root, "state");
  const dataRoot = path.join(root, "session-recap");
  const configPath = path.join(root, "config.toml");
  await writeFile(configPath, '[theme]\nname = "nord"\nauto_switch = false\n');
  const session = { source: "herdr:pi", agent: "pi", kind: "id", value: "pi-1" };
  const current = snapshot({
    agents: [{ pane_id: "ws-a:p1", agent: "pi", display_agent: "Pi", agent_session: session }],
  });
  current.panes[0].agent = "pi";
  current.panes[0].agent_session = session;
  const renameCalls = [];
  const api = {
    async snapshot() { return current; },
    async readPane() { return "terminal preview is not a task label"; },
    async processInfo() { return { foreground_processes: [{ name: "pi" }] }; },
    async renamePane(id, label) { renameCalls.push({ kind: "pane", id, label }); current.panes.find((pane) => pane.pane_id === id).label = label; },
    async renameTab(id, label) { renameCalls.push({ kind: "tab", id, label }); current.tabs.find((tab) => tab.tab_id === id).label = label; },
  };
  const reconcile = () => reconcileOverview({ api, stateDir, dataRoot, configPath, openPane: false });
  const record = async ({ id, status, summary, workspaceId = "ws-a" }) => {
    const item = {
      record_id: id,
      source_kind: "pi-session",
      source_id: "pi-1",
      pane_id: "ws-a:p1",
      ...(workspaceId ? { workspace_id: workspaceId } : {}),
      status,
      ...(summary ? { summary } : {}),
      created_at: "2026-09-26T00:00:00Z",
      ...(status === "published" ? { published_at: "2026-09-26T00:00:00Z" } : {}),
    };
    const recordsDir = path.join(dataRoot, "records", "2026-09-26");
    await mkdir(recordsDir, { recursive: true });
    await writeFile(path.join(recordsDir, `${id}.json`), `${JSON.stringify(item)}\n`);
    return item;
  };
  const writeLatest = async (latestId, attemptId = latestId) => {
    await mkdir(dataRoot, { recursive: true });
    await writeFile(path.join(dataRoot, "latest.json"), `${JSON.stringify({ schema_version: 1, sources: [
      { source_kind: "pi-session", source_id: "pi-1", latest_success_id: latestId, last_attempt_id: attemptId },
    ] })}\n`);
  };

  const initial = await reconcile();
  assert.equal(initial.model.panes["ws-a:p1"].label, null);
  assert.deepEqual(renameCalls, []);

  const firstId = "a".repeat(32);
  await record({ id: firstId, status: "published", summary: "Migrate authentication" });
  await mkdir(path.join(dataRoot, "prompts"), { recursive: true });
  await writeFile(path.join(dataRoot, "prompts", "pi-1.json"), `${JSON.stringify({
    schema_version: 1, session_id: "pi-1", pane_id: "ws-a:p1", text: "LIVE PROMPT ONLY", working: false,
    captured_at: "2026-09-26T00:00:00Z",
  })}\n`);
  await writeLatest(firstId);
  const published = await reconcile();
  assert.equal(published.model.panes["ws-a:p1"].label, "Migrate authentication");
  assert.equal(published.model.panes["ws-a:p1"].prompt.text, "LIVE PROMPT ONLY");
  assert.equal(published.model.panes["ws-a:p1"].agent.session.value, "pi-1");
  assert.equal(published.model.workspaces["ws-a"].label, "Do not rename");
  assert.equal(renameCalls.length, 2);

  const failedId = "b".repeat(32);
  await record({ id: failedId, status: "failed" });
  await writeLatest(firstId, failedId);
  await reconcile();
  assert.equal(renameCalls.length, 2, "a failed attempt does not change an automatic name");

  const outsideId = "c".repeat(32);
  await record({ id: outsideId, status: "published", summary: "Must not name an in-workspace pane", workspaceId: null });
  await writeLatest(outsideId);
  const outside = await reconcile();
  assert.equal(outside.model.panes["ws-a:p1"].label, "Migrate authentication");
  assert.equal(renameCalls.length, 2, "an out-of-workspace publication is not a naming event");

  const secondId = "d".repeat(32);
  await record({ id: secondId, status: "published", summary: "Ship migration" });
  await writeLatest(secondId);
  const nextPublished = await reconcile();
  assert.equal(nextPublished.model.panes["ws-a:p1"].label, "Ship migration");
  assert.equal(nextPublished.model.tabs["ws-a:t1"].label, "Ship migration");
  assert.equal(renameCalls.length, 4);
});

test("auto-name pane action completes through the plugin entrypoint and scripted Herdr socket", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "herdr-name-action-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const socketPath = path.join(root, "herdr.sock");
  const configPath = path.join(root, "config.toml");
  const stateDir = path.join(root, "state");
  await writeFile(configPath, '[theme]\nname = "nord"\nauto_switch = false\n');
  const nativeSnapshot = {
    protocol: 22,
    version: "0.9.1",
    focused_workspace_id: "ws-a",
    focused_tab_id: "ws-a:t1",
    focused_pane_id: "ws-a:p1",
    workspaces: [{ workspace_id: "ws-a", number: 1, label: "Keep workspace", focused: true, active_tab_id: "ws-a:t1", agent_status: "unknown" }],
    tabs: [{ tab_id: "ws-a:t1", workspace_id: "ws-a", number: 1, label: "Manual tab", pane_count: 1, agent_status: "unknown" }],
    panes: [{ pane_id: "ws-a:p1", workspace_id: "ws-a", tab_id: "ws-a:t1", label: "Manual pane", cwd: "/repo/app", focused: true, agent_status: "unknown" }],
    agents: [],
  };
  const calls = [];
  const server = net.createServer((socket) => {
    let buffer = "";
    socket.on("data", (chunk) => {
      buffer += chunk.toString("utf8");
      let newline;
      while ((newline = buffer.indexOf("\n")) >= 0) {
        const request = JSON.parse(buffer.slice(0, newline));
        buffer = buffer.slice(newline + 1);
        calls.push(request);
        let result = { type: "ok" };
        if (request.method === "session.snapshot") result = { snapshot: nativeSnapshot };
        if (request.method === "pane.read") result = { read: { text: "preview" } };
        if (request.method === "pane.process_info") result = { process_info: { foreground_processes: [{ name: "node" }] } };
        if (request.method === "pane.rename") nativeSnapshot.panes[0].label = request.params.label;
        socket.write(`${JSON.stringify({ id: request.id, result })}\n`);
      }
    });
  });
  await new Promise((resolve, reject) => server.listen(socketPath, (error) => error ? reject(error) : resolve()));
  t.after(() => new Promise((resolve) => server.close(resolve)));

  const pluginRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
  const child = spawn(process.execPath, [path.join(pluginRoot, "index.mjs"), "auto-name-pane"], {
    cwd: pluginRoot,
    env: {
      ...process.env,
      HERDR_SOCKET_PATH: socketPath,
      HERDR_CONFIG_PATH: configPath,
      HERDR_PLUGIN_STATE_DIR: stateDir,
      XDG_DATA_HOME: path.join(root, "data"),
      HERDR_PLUGIN_CONTEXT_JSON: JSON.stringify({ focused_pane_id: "ws-a:p1", tab_id: "ws-a:t1" }),
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let stdout = "";
  let stderr = "";
  child.stdout.setEncoding("utf8").on("data", (chunk) => { stdout += chunk; });
  child.stderr.setEncoding("utf8").on("data", (chunk) => { stderr += chunk; });
  const exitCode = await new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("close", resolve);
  });
  assert.equal(exitCode, 0, `${stdout}\n${stderr}`);
  assert.deepEqual(calls.map((call) => call.method), ["session.snapshot", "pane.read", "pane.process_info", "session.snapshot", "pane.rename"]);
  assert.deepEqual(calls.at(-1).params, { pane_id: "ws-a:p1", label: "node · app" });
  assert.equal(nativeSnapshot.panes[0].label, "node · app");
  assert.equal(nativeSnapshot.tabs[0].label, "Manual tab");
  assert.equal(nativeSnapshot.workspaces[0].label, "Keep workspace");
  const state = JSON.parse(await readFile(path.join(stateDir, "overview.json"), "utf8"));
  assert.equal(state.displayNameOwnership["pane:ws-a:p1"].mode, "automatic");
  assert.equal(state.displayNameOwnership["pane:ws-a:p1"].lastWrittenLabel, "node · app");
});

test("an automatic multi-agent tab represents both published Pi tasks", () => {
  const agents = [1, 2].map((index) => ({
    pane_id: `ws-a:p${index}`,
    agent: "pi",
    agent_session: { source: "herdr:pi", agent: "pi", kind: "id", value: `pi-${index}` },
  }));
  const current = snapshot({ agents, paneLabels: [null, null] });
  for (const pane of current.panes) {
    const session = agents.find((agent) => agent.pane_id === pane.pane_id).agent_session;
    pane.agent = "pi";
    pane.agent_session = session;
  }
  const result = evaluateDisplayNamePolicy(current, {
    supplied: {
      promptsBySessionId: {
        "pi-1": { text: "Ignore live prompt one" },
        "pi-2": { text: "Ignore live prompt two" },
      },
      piRecapsBySessionId: {
        "pi-1": publishedRecap("ws-a:p1", "Migrate auth"),
        "pi-2": publishedRecap("ws-a:p2", "Add cache"),
      },
    },
  });

  assert.deepEqual(result.rename.filter((entry) => entry.kind === "tab"), [
    { kind: "tab", id: "ws-a:t1", label: "Migrate auth + Add cache" },
  ]);
});

test("overview.reconcile persists ownership, preserves manual edits, and applies only the selected reset", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "herdr-display-names-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const stateDir = path.join(root, "state");
  const configPath = path.join(root, "config.toml");
  await writeFile(configPath, '[theme]\nname = "nord"\nauto_switch = false\n');
  const current = snapshot();
  const renameCalls = [];
  const api = {
    async snapshot() { return current; },
    async readPane() { return "output is not a task label"; },
    async processInfo() { return { foreground_processes: [{ name: "zsh" }] }; },
    async renamePane(id, label) { renameCalls.push({ kind: "pane", id, label }); current.panes.find((pane) => pane.pane_id === id).label = label; },
    async renameTab(id, label) { renameCalls.push({ kind: "tab", id, label }); current.tabs.find((tab) => tab.tab_id === id).label = label; },
  };

  const first = await reconcileOverview({ api, stateDir, configPath, openPane: false });
  assert.deepEqual(renameCalls, [
    { kind: "pane", id: "ws-a:p1", label: "zsh · app" },
    { kind: "tab", id: "ws-a:t1", label: "zsh · app" },
  ]);
  assert.equal(first.model.panes["ws-a:p1"].label, "zsh · app");
  assert.equal(first.model.panes["ws-a:p1"].displayNameOwnership.mode, "automatic");
  assert.equal(first.model.tabs["ws-a:t1"].displayNameOwnership.lastWrittenLabel, "zsh · app");

  current.panes[0].label = "Owner pane";
  current.tabs[0].label = "Owner tab";
  const beforeReset = await reconcileOverview({ api, stateDir, configPath, openPane: false });
  assert.equal(renameCalls.length, 2);
  assert.equal(beforeReset.model.panes["ws-a:p1"].displayNameOwnership.mode, "manual");
  assert.equal(beforeReset.model.tabs["ws-a:t1"].displayNameOwnership.mode, "manual");

  const paneReset = await reconcileOverview({
    api, stateDir, configPath, openPane: false,
    resetName: { kind: "pane", id: "ws-a:p1" },
  });
  assert.equal(renameCalls.at(-1).kind, "pane");
  assert.equal(paneReset.model.panes["ws-a:p1"].displayNameOwnership.mode, "automatic");
  assert.equal(paneReset.model.tabs["ws-a:t1"].displayNameOwnership.mode, "manual");
  assert.equal(paneReset.model.workspaces["ws-a"].label, "Do not rename");
  assert.equal(current.agents.length, 0, "reconciliation did not create or rename agent identities");
  assert.equal(current.panes[0].agent_session, undefined);

  const persisted = JSON.parse(await readFile(path.join(stateDir, "overview.json"), "utf8"));
  assert.equal(persisted.displayNameOwnership["pane:ws-a:p1"].mode, "automatic");
});
