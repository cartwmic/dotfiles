import test from "node:test";
import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { reconcileOverview } from "../src/coordinator.mjs";
import { readAllRecapRecords } from "../src/recap-store.mjs";
import { runSessionRecap } from "../src/recap-coordinator.mjs";
import { runDeadlineWakeup } from "../src/deadline-wakeup.mjs";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../../");
const recapCli = path.join(repoRoot, "dot_local", "bin", "executable_session-recap");
const fakeBackend = path.join(repoRoot, "tests", "herdr-overview", "fake_recap_backend.py");

async function makeRuntime(t) {
  const root = await mkdtemp(path.join(os.tmpdir(), "herdr-recap-coordinator-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const configHome = path.join(root, "config");
  const dataHome = path.join(root, "data");
  const stateHome = path.join(root, "state-home");
  const dataRoot = path.join(dataHome, "session-recap");
  const stateDir = path.join(root, "herdr-state");
  const configPath = path.join(root, "herdr-config.toml");
  const modePath = path.join(root, "backend-mode");
  const captureLog = path.join(root, "backend-calls.jsonl");
  const recapConfigDir = path.join(configHome, "session-recap");
  await mkdir(recapConfigDir, { recursive: true });
  await writeFile(path.join(recapConfigDir, "config.toml"), `command = ["python3", ${JSON.stringify(fakeBackend)}]\n`);
  await writeFile(path.join(recapConfigDir, "single-prompt.md"), "single:\n[[TEXT]]\n");
  await writeFile(path.join(recapConfigDir, "group-prompt.md"), "group:\n[[MEMBERS]]\n");
  await writeFile(configPath, '[theme]\nname = "nord"\nauto_switch = false\n');
  await writeFile(modePath, "success\n");

  const env = {
    ...process.env,
    XDG_CONFIG_HOME: configHome,
    XDG_DATA_HOME: dataHome,
    XDG_STATE_HOME: stateHome,
    SESSION_RECAP_BIN: recapCli,
    FAKE_RECAP_MODE_FILE: modePath,
    FAKE_RECAP_CAPTURE_LOG: captureLog,
  };
  const runRecap = (args, input = "") => runSessionRecap(args, input, { bin: recapCli, env });
  const setBackendMode = (mode) => writeFile(modePath, `${mode}\n`);
  return { root, configPath, dataRoot, stateDir, captureLog, env, runRecap, setBackendMode };
}

function scriptedHerdrApi(initialMembership) {
  const membership = new Map(Object.entries(initialMembership));
  const api = {
    socketPath: null,
    setMembership(paneId, workspaceId) { membership.set(paneId, workspaceId); },
    async snapshot() {
      const panes = [...membership.entries()].map(([pane_id, workspace_id], index) => ({
        pane_id,
        workspace_id,
        tab_id: `${workspace_id}:tab`,
        terminal_id: `terminal-${index}`,
        focused: index === 0,
        agent_status: "unknown",
        revision: 1,
        cwd: "/workspace",
        label: null,
      }));
      const workspaceIds = [...new Set(panes.map((pane) => pane.workspace_id))];
      const tabs = workspaceIds.map((workspace_id, index) => ({
        tab_id: `${workspace_id}:tab`, workspace_id, number: 1, label: "Main",
        focused: index === 0, pane_count: panes.filter((pane) => pane.workspace_id === workspace_id).length,
        agent_status: "unknown",
      }));
      return {
        protocol: 22,
        version: "0.9.1",
        focused_workspace_id: workspaceIds[0] ?? null,
        focused_tab_id: tabs[0]?.tab_id ?? null,
        focused_pane_id: panes[0]?.pane_id ?? null,
        workspaces: workspaceIds.map((workspace_id, index) => ({
          workspace_id, number: index + 1, label: workspace_id, focused: index === 0,
          pane_count: panes.filter((pane) => pane.workspace_id === workspace_id).length,
          tab_count: 1, active_tab_id: `${workspace_id}:tab`, agent_status: "unknown",
        })),
        tabs, panes, agents: [], layouts: [],
      };
    },
    async readPane() { return "live output"; },
    async processInfo() { return null; },
  };
  return api;
}

function coordinatorOptions(runtime, api, { now = Date.now(), resumeDeadlines = false } = {}) {
  return {
    api,
    stateDir: runtime.stateDir,
    dataRoot: runtime.dataRoot,
    configPath: runtime.configPath,
    openPane: false,
    coordinatorWake: true,
    resumeDeadlines,
    coordinatorNow: () => now,
    recapRunner: runtime.runRecap,
    env: runtime.env,
    scheduleWakeup: (wakeup) => runtime.scheduled.push(wakeup),
  };
}

async function reconcile(runtime, api, options = {}) {
  return reconcileOverview(coordinatorOptions(runtime, api, options));
}

async function publishPi(runtime, { sessionId, paneId, workspaceId, text = "Completed a useful unit of work." }) {
  const prepareArgs = ["prepare", "--source-id", sessionId];
  if (paneId) prepareArgs.push("--pane-id", paneId);
  const preparedId = await runtime.runRecap(prepareArgs, text);
  const publishArgs = ["publish", "--prepared-id", preparedId];
  if (workspaceId) publishArgs.push("--workspace-id", workspaceId);
  const recordId = await runtime.runRecap(publishArgs);
  return (await readAllRecapRecords(runtime.dataRoot)).find((record) => record.record_id === recordId);
}

async function readLatestIndex(dataRoot) {
  return JSON.parse(await readFile(path.join(dataRoot, "latest.json"), "utf8"));
}

async function readState(stateDir) {
  return JSON.parse(await readFile(path.join(stateDir, "overview.json"), "utf8"));
}

function latestSource(index, sourceKind, sourceId) {
  return index.sources.find((source) => source.source_kind === sourceKind && source.source_id === sourceId);
}

test("replay keeps publication-time workspace membership; only a newer in-workspace success resets the deadline", async (t) => {
  const runtime = await makeRuntime(t);
  runtime.scheduled = [];
  const api = scriptedHerdrApi({ "pane-one": "workspace-original" });
  const first = await publishPi(runtime, {
    sessionId: "pi-session-one", paneId: "pane-one", workspaceId: "workspace-original", text: "First pane recap",
  });
  const firstDeadline = new Date(Date.parse(first.published_at) + 30_000).toISOString();

  // The publication is deliberately left unprocessed until a simulated server restart.
  api.setMembership("pane-one", "workspace-now");
  let state = await reconcile(runtime, api, { now: Date.now(), resumeDeadlines: true });
  assert.equal(state.recapCoordinator.workspaceDeadlines["workspace-original"], firstDeadline);
  assert.equal(state.recapCoordinator.workspaceDeadlines["workspace-now"], undefined);
  assert.ok(state.recapCoordinator.processedRecordIds.includes(first.record_id));

  state = await reconcile(runtime, api, { now: Date.now(), resumeDeadlines: true });
  assert.equal(state.recapCoordinator.workspaceDeadlines["workspace-original"], firstDeadline);
  assert.equal(state.recapCoordinator.processedRecordIds.filter((id) => id === first.record_id).length, 1);

  // Failed, blank, prepared-but-unpublished, and no-workspace records are not resets.
  await runtime.setBackendMode("blank");
  await assert.rejects(runtime.runRecap(["prepare", "--source-id", "pi-session-one", "--pane-id", "pane-one"], "blank result"));
  await runtime.setBackendMode("success");
  const unpublished = await runtime.runRecap(["prepare", "--source-id", "pi-unpublished", "--pane-id", "pane-one"], "prepared only");
  assert.ok(unpublished);
  const noWorkspace = await publishPi(runtime, {
    sessionId: "pi-without-workspace", paneId: "pane-outside", text: "Published without Herdr membership",
  });
  state = await reconcile(runtime, api, { now: Date.now() });
  assert.equal(state.recapCoordinator.workspaceDeadlines["workspace-original"], firstDeadline);
  assert.equal(state.recapCoordinator.workspaceDeadlines["workspace-now"], undefined);
  assert.ok(state.recapCoordinator.processedRecordIds.includes(noWorkspace.record_id));

  await new Promise((resolve) => setTimeout(resolve, 5));
  const secondPane = await publishPi(runtime, {
    sessionId: "pi-session-two", paneId: "pane-two", workspaceId: "workspace-original", text: "Second pane recap",
  });
  state = await reconcile(runtime, api, { now: Date.now() });
  const resetDeadline = new Date(Date.parse(secondPane.published_at) + 30_000).toISOString();
  assert.equal(state.recapCoordinator.workspaceDeadlines["workspace-original"], resetDeadline);
  assert.ok(Date.parse(resetDeadline) >= Date.parse(firstDeadline));
  assert.equal(state.recapCoordinator.workspaceDeadlines["workspace-now"], undefined);

  // Restart/replay after the pane moved still groups records using their stored publication workspace.
  const dueState = await reconcile(runtime, api, { now: Date.parse(resetDeadline), resumeDeadlines: true });
  assert.equal(dueState.recapCoordinator.workspaceDeadlines["workspace-original"], undefined);
  const records = await readAllRecapRecords(runtime.dataRoot);
  const workspaceRecap = records.find((record) => record.source_kind === "workspace" && record.status === "published");
  assert.ok(workspaceRecap);
  assert.deepEqual(new Set(workspaceRecap.member_record_ids), new Set([first.record_id, secondPane.record_id]));
  const index = await readLatestIndex(runtime.dataRoot);
  assert.equal(latestSource(index, "workspace", "workspace-original").latest_success_id, workspaceRecap.record_id);
});

test("a quiet deadline waits the full interval, groups latest pane recaps once, then publishes the active-session recap", async (t) => {
  const runtime = await makeRuntime(t);
  runtime.scheduled = [];
  const api = scriptedHerdrApi({ "pane-one": "workspace-a", "pane-two": "workspace-a" });

  const paneOneOld = await publishPi(runtime, {
    sessionId: "pi-one", paneId: "pane-one", workspaceId: "workspace-a", text: "Older pane-one work",
  });
  let state = await reconcile(runtime, api, { now: Date.now() });
  const initialDeadline = state.recapCoordinator.workspaceDeadlines["workspace-a"];
  assert.equal(Date.parse(initialDeadline) - Date.parse(paneOneOld.published_at), 30_000);
  assert.equal(runtime.scheduled.at(-1).deadline, initialDeadline);

  await new Promise((resolve) => setTimeout(resolve, 5));
  const paneTwo = await publishPi(runtime, {
    sessionId: "pi-two", paneId: "pane-two", workspaceId: "workspace-a", text: "Pane-two current work",
  });
  state = await reconcile(runtime, api, { now: Date.now() });
  const paneTwoDeadline = state.recapCoordinator.workspaceDeadlines["workspace-a"];
  assert.equal(Date.parse(paneTwoDeadline) - Date.parse(paneTwo.published_at), 30_000);
  assert.ok(Date.parse(paneTwoDeadline) > Date.parse(initialDeadline));

  await new Promise((resolve) => setTimeout(resolve, 5));
  const paneOneLatest = await publishPi(runtime, {
    sessionId: "pi-one", paneId: "pane-one", workspaceId: "workspace-a", text: "Latest pane-one work",
  });
  state = await reconcile(runtime, api, { now: Date.now() });
  const deadline = state.recapCoordinator.workspaceDeadlines["workspace-a"];
  assert.equal(Date.parse(deadline) - Date.parse(paneOneLatest.published_at), 30_000);
  assert.ok(Date.parse(deadline) > Date.parse(paneTwoDeadline));

  // Herdr now reports pane-one in another workspace. Replay must use its publication record instead.
  api.setMembership("pane-one", "workspace-moved-later");
  await reconcile(runtime, api, { now: Date.parse(deadline) - 1 });
  let records = await readAllRecapRecords(runtime.dataRoot);
  assert.equal(records.filter((record) => record.source_kind === "workspace" && record.status === "published").length, 0);

  // Startup resumes the persisted elapsed deadline and drains without reprocessing prior record IDs.
  state = await reconcile(runtime, api, { now: Date.parse(deadline), resumeDeadlines: true });
  assert.equal(state.recapCoordinator.workspaceDeadlines["workspace-a"], undefined);
  const processedCount = state.recapCoordinator.processedRecordIds.length;
  state = await reconcile(runtime, api, { now: Date.parse(deadline), resumeDeadlines: true });
  assert.equal(state.recapCoordinator.processedRecordIds.length, processedCount);

  records = await readAllRecapRecords(runtime.dataRoot);
  const workspacePublished = records.filter((record) => record.source_kind === "workspace" && record.status === "published");
  const sessionPublished = records.filter((record) => record.source_kind === "herdr-session" && record.status === "published");
  assert.equal(workspacePublished.length, 1, "one workspace publication for the quiet window");
  assert.equal(sessionPublished.length, 1, "the session publication follows workspace success exactly once");
  assert.deepEqual(new Set(workspacePublished[0].member_record_ids), new Set([paneTwo.record_id, paneOneLatest.record_id]));
  assert.ok(!workspacePublished[0].member_record_ids.includes(paneOneOld.record_id), "older recap for the same pane is retained but not grouped");
  assert.deepEqual(sessionPublished[0].member_record_ids, [workspacePublished[0].record_id]);

  const index = await readLatestIndex(runtime.dataRoot);
  assert.equal(latestSource(index, "workspace", "workspace-a").latest_success_id, workspacePublished[0].record_id);
  assert.equal(latestSource(index, "herdr-session", "active").latest_success_id, sessionPublished[0].record_id);
  assert.ok(records.some((record) => record.record_id === paneOneOld.record_id), "superseded individual recap history remains on disk");
  const backendCalls = (await readFile(runtime.captureLog, "utf8")).trim().split("\n").map((line) => JSON.parse(line));
  assert.equal(backendCalls.filter((call) => call.prompt.startsWith("group:")).length, 2);
});

test("one-shot deadline wake-ups invoke only overview.reconcile and ignore superseded deadlines", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "herdr-recap-deadline-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const stateDir = path.join(root, "state");
  await mkdir(stateDir, { recursive: true });
  const workspaceId = "workspace-one-shot";
  const deadline = new Date(Date.now() + 25).toISOString();
  await writeFile(path.join(stateDir, "overview.json"), JSON.stringify({
    recapCoordinator: { workspaceDeadlines: { [workspaceId]: deadline } },
  }));
  const calls = [];
  const api = { async request(method, params) { calls.push({ method, params }); } };
  const wake = runDeadlineWakeup({ workspaceId, deadline, stateDir, socketPath: "/tmp/herdr-test.sock", api });
  await new Promise((resolve) => setTimeout(resolve, 5));
  const replacement = new Date(Date.parse(deadline) + 30_000).toISOString();
  await writeFile(path.join(stateDir, "overview.json"), JSON.stringify({
    recapCoordinator: { workspaceDeadlines: { [workspaceId]: replacement } },
  }));
  assert.equal(await wake, false, "a reset quiet interval makes the old one-shot timer a no-op");
  assert.deepEqual(calls, []);

  const due = new Date(Date.now() - 1).toISOString();
  await writeFile(path.join(stateDir, "overview.json"), JSON.stringify({
    recapCoordinator: { workspaceDeadlines: { [workspaceId]: due } },
  }));
  assert.equal(await runDeadlineWakeup({ workspaceId, deadline: due, stateDir, socketPath: "/tmp/herdr-test.sock", api }), true);
  assert.deepEqual(calls, [{ method: "plugin.action.invoke", params: { action_id: "overview.reconcile" } }]);
});

test("failed workspace grouping records failure and never triggers session grouping", async (t) => {
  const runtime = await makeRuntime(t);
  runtime.scheduled = [];
  const api = scriptedHerdrApi({ "pane-one": "workspace-failure" });
  const piRecap = await publishPi(runtime, {
    sessionId: "pi-failure", paneId: "pane-one", workspaceId: "workspace-failure", text: "Ready for grouping",
  });
  let state = await reconcile(runtime, api, { now: Date.now() });
  const deadline = state.recapCoordinator.workspaceDeadlines["workspace-failure"];

  await runtime.setBackendMode("nonzero");
  state = await reconcile(runtime, api, { now: Date.parse(deadline), resumeDeadlines: true });
  assert.equal(state.recapCoordinator.workspaceDeadlines["workspace-failure"], deadline, "failed one-shot remains due for a later wake-up");
  let index = await readLatestIndex(runtime.dataRoot);
  const failedWorkspaceSource = latestSource(index, "workspace", "workspace-failure");
  assert.ok(failedWorkspaceSource);
  assert.equal(failedWorkspaceSource.latest_success_id, null);
  assert.equal(latestSource(index, "herdr-session", "active"), undefined);
  let records = await readAllRecapRecords(runtime.dataRoot);
  const failedAttempt = records.find((record) => record.record_id === failedWorkspaceSource.last_attempt_id);
  assert.equal(failedAttempt.status, "failed");
  assert.deepEqual(failedAttempt.member_record_ids, [piRecap.record_id]);
  assert.equal(records.filter((record) => record.source_kind === "herdr-session").length, 0);

  await runtime.setBackendMode("success");
  state = await reconcile(runtime, api, { now: Date.parse(deadline) });
  assert.equal(state.recapCoordinator.workspaceDeadlines["workspace-failure"], undefined);
  index = await readLatestIndex(runtime.dataRoot);
  const workspaceSource = latestSource(index, "workspace", "workspace-failure");
  const sessionSource = latestSource(index, "herdr-session", "active");
  assert.ok(workspaceSource.latest_success_id);
  assert.ok(sessionSource.latest_success_id);
  records = await readAllRecapRecords(runtime.dataRoot);
  const successfulWorkspace = records.find((record) => record.record_id === workspaceSource.latest_success_id);
  const successfulSession = records.find((record) => record.record_id === sessionSource.latest_success_id);
  assert.deepEqual(successfulWorkspace.member_record_ids, [piRecap.record_id]);
  assert.deepEqual(successfulSession.member_record_ids, [successfulWorkspace.record_id]);
});
