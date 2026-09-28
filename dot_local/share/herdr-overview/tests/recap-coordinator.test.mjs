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
  const recapConfigPath = path.join(recapConfigDir, "config.toml");
  const recapCommand = `command = ["python3", ${JSON.stringify(fakeBackend)}]\n`;
  const setAutoPublish = (enabled) => writeFile(recapConfigPath, `auto_publish = ${enabled}\n${recapCommand}`);
  await setAutoPublish(true);
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
  return { root, configPath, dataRoot, stateDir, captureLog, env, runRecap, setBackendMode, setAutoPublish };
}

function scriptedHerdrApi(initialMembership, initialTerminalIds = {}, initialAgentNames = {}) {
  const membership = new Map(Object.entries(initialMembership));
  const terminalIds = new Map();
  const agentNames = new Map(Object.entries(initialAgentNames));
  for (const paneId of membership.keys()) terminalIds.set(paneId, initialTerminalIds[paneId] ?? `terminal-${paneId}`);
  const api = {
    socketPath: null,
    setMembership(paneId, workspaceId, terminalId = terminalIds.get(paneId)) {
      membership.set(paneId, workspaceId);
      if (terminalId) terminalIds.set(paneId, terminalId);
    },
    movePane(previousPaneId, newPaneId, workspaceId) {
      const terminalId = terminalIds.get(previousPaneId);
      membership.delete(previousPaneId);
      terminalIds.delete(previousPaneId);
      membership.set(newPaneId, workspaceId);
      if (terminalId) terminalIds.set(newPaneId, terminalId);
      const agentName = agentNames.get(previousPaneId);
      agentNames.delete(previousPaneId);
      if (agentName) agentNames.set(newPaneId, agentName);
    },
    removePane(paneId) {
      membership.delete(paneId);
      terminalIds.delete(paneId);
      agentNames.delete(paneId);
    },
    async snapshot() {
      const panes = [...membership.entries()].map(([pane_id, workspace_id], index) => ({
        pane_id,
        workspace_id,
        tab_id: `${workspace_id}:tab`,
        terminal_id: terminalIds.get(pane_id),
        focused: index === 0,
        agent: agentNames.get(pane_id) ?? "pi",
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
        tabs,
        panes,
        // Herdr's real Pi snapshot can report agent=pi but agent_session=null.
        agents: panes.map((pane) => ({ pane_id: pane.pane_id, agent: pane.agent })),
        layouts: [],
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

async function publishManualPane(runtime, paneId, { label, text = "Manual pane recap." } = {}) {
  const args = ["create", "--kind", "single", "--source-id", paneId];
  if (label) args.push("--label", label);
  const recordId = await runtime.runRecap(args, text);
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

test("replay preserves publication-time deadlines while grouping rekeyed panes by current membership", async (t) => {
  const runtime = await makeRuntime(t);
  runtime.scheduled = [];
  let api = scriptedHerdrApi({
    "pane-one": "workspace-original",
    "pane-two": "workspace-original",
    "pane-three": "workspace-now",
    "pane-four": "workspace-original",
  }, {
    "pane-one": "terminal-one",
    "pane-two": "terminal-two",
    "pane-three": "terminal-three",
    "pane-four": "terminal-four",
  });
  const first = await publishPi(runtime, {
    sessionId: "pi-session-one", paneId: "pane-one", workspaceId: "workspace-original", text: "First pane recap",
  });
  const firstDeadline = new Date(Date.parse(first.published_at) + 30_000).toISOString();

  // The publication-time snapshot has no agent_session, so persist its stable
  // terminal association before Herdr rekeys the pane ID on a native move.
  let state = await reconcile(runtime, api, { now: Date.now(), resumeDeadlines: true });
  assert.equal(state.recapCoordinator.piTerminalIdsBySessionId["pi-session-one"], "terminal-one");

  // Replay keeps the original deadline attribution but follows the same
  // terminal_id into the current workspace, even with no agent_session field.
  api.movePane("pane-one", "pane-one-rekeyed", "workspace-now");
  const movedSnapshot = await api.snapshot();
  assert.equal(movedSnapshot.panes.some((pane) => pane.pane_id === "pane-one"), false);
  assert.equal(movedSnapshot.panes.find((pane) => pane.pane_id === "pane-one-rekeyed").terminal_id, "terminal-one");
  assert.equal(Object.hasOwn(movedSnapshot.panes.find((pane) => pane.pane_id === "pane-one-rekeyed"), "agent_session"), false);
  assert.equal(Object.hasOwn(movedSnapshot.agents.find((agent) => agent.pane_id === "pane-one-rekeyed"), "agent_session"), false);
  // A fresh adapter after a server restart reads only the new native IDs; the
  // plugin's persisted terminal association is what recovers the old recap.
  api = scriptedHerdrApi(
    Object.fromEntries(movedSnapshot.panes.map((pane) => [pane.pane_id, pane.workspace_id])),
    Object.fromEntries(movedSnapshot.panes.map((pane) => [pane.pane_id, pane.terminal_id])),
  );
  state = await reconcile(runtime, api, { now: Date.now(), resumeDeadlines: true });
  assert.equal(state.model.panes["pane-one-rekeyed"].recap.latest.record_id, first.record_id);
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

  const closedPane = await publishPi(runtime, {
    sessionId: "pi-session-four", paneId: "pane-four", workspaceId: "workspace-original", text: "Work from a pane that will close",
  });
  state = await reconcile(runtime, api, { now: Date.now() });
  assert.equal(
    state.recapCoordinator.workspaceDeadlines["workspace-original"],
    new Date(Date.parse(closedPane.published_at) + 30_000).toISOString(),
  );
  api.removePane("pane-four");

  await new Promise((resolve) => setTimeout(resolve, 5));
  const secondPane = await publishPi(runtime, {
    sessionId: "pi-session-two", paneId: "pane-two", workspaceId: "workspace-original", text: "Second pane recap",
  });
  state = await reconcile(runtime, api, { now: Date.now() });
  const resetDeadline = new Date(Date.parse(secondPane.published_at) + 30_000).toISOString();
  assert.equal(state.recapCoordinator.workspaceDeadlines["workspace-original"], resetDeadline);
  assert.ok(Date.parse(resetDeadline) >= Date.parse(firstDeadline));

  await new Promise((resolve) => setTimeout(resolve, 5));
  const movedPaneWorkspaceRecap = await publishPi(runtime, {
    sessionId: "pi-session-three", paneId: "pane-three", workspaceId: "workspace-now", text: "Current workspace work",
  });
  state = await reconcile(runtime, api, { now: Date.now() });
  const movedWorkspaceDeadline = new Date(Date.parse(movedPaneWorkspaceRecap.published_at) + 30_000).toISOString();
  assert.equal(state.recapCoordinator.workspaceDeadlines["workspace-original"], resetDeadline);
  assert.equal(state.recapCoordinator.workspaceDeadlines["workspace-now"], movedWorkspaceDeadline);

  const dueAt = Math.max(Date.parse(resetDeadline), Date.parse(movedWorkspaceDeadline));
  const dueState = await reconcile(runtime, api, { now: dueAt, resumeDeadlines: true });
  assert.equal(dueState.recapCoordinator.workspaceDeadlines["workspace-original"], undefined);
  assert.equal(dueState.recapCoordinator.workspaceDeadlines["workspace-now"], undefined);
  const records = await readAllRecapRecords(runtime.dataRoot);
  const workspaceOriginal = records.find((record) => record.source_kind === "workspace" && record.source_id === "workspace-original" && record.status === "published");
  const workspaceNow = records.find((record) => record.source_kind === "workspace" && record.source_id === "workspace-now" && record.status === "published");
  assert.ok(workspaceOriginal);
  assert.ok(workspaceNow);
  assert.deepEqual(workspaceOriginal.member_record_ids, [secondPane.record_id], "moved and closed panes are excluded from current workspace members");
  assert.ok(!workspaceOriginal.member_record_ids.includes(closedPane.record_id), "a closed pane is not grouped");
  assert.deepEqual(new Set(workspaceNow.member_record_ids), new Set([first.record_id, movedPaneWorkspaceRecap.record_id]), "the rekeyed pane's latest recap follows its current Pi session into the new workspace");

  const index = await readLatestIndex(runtime.dataRoot);
  assert.equal(latestSource(index, "workspace", "workspace-original").latest_success_id, workspaceOriginal.record_id);
  assert.equal(latestSource(index, "workspace", "workspace-now").latest_success_id, workspaceNow.record_id);
  const activeSessionId = latestSource(index, "herdr-session", "active").latest_success_id;
  const activeSessionRecap = records.find((record) => record.record_id === activeSessionId);
  assert.ok(activeSessionRecap);
  assert.deepEqual(new Set(activeSessionRecap.member_record_ids), new Set([workspaceOriginal.record_id, workspaceNow.record_id]));
});

test("workspace groups include latest manual pane recaps and session groups exclude closed workspaces", async (t) => {
  const runtime = await makeRuntime(t);
  runtime.scheduled = [];
  const api = scriptedHerdrApi({
    "pi-pane": "workspace-live",
    "shell-pane": "workspace-live",
    "closed-pane": "workspace-closed",
  }, {}, { "shell-pane": "claude" });

  const oldManual = await publishManualPane(runtime, "shell-pane", { label: "Old shell recap" });
  const currentManual = await publishManualPane(runtime, "shell-pane", { label: "Current shell recap" });
  const closedMember = await publishManualPane(runtime, "closed-pane", { label: "Closed workspace recap" });
  const closedWorkspaceId = await runtime.runRecap(
    ["create", "--kind", "group", "--source-kind", "workspace", "--source-id", "workspace-closed"],
    `${JSON.stringify({ members: [{ record_id: closedMember.record_id, text: closedMember.summary, label: closedMember.label }] })}\n`,
  );
  const closedWorkspace = (await readAllRecapRecords(runtime.dataRoot))
    .find((record) => record.record_id === closedWorkspaceId);
  assert.equal(closedWorkspace.source_id, "workspace-closed");

  // A manual pane recap is a member, not a quiet-deadline trigger.
  api.removePane("closed-pane");
  const currentSnapshot = await api.snapshot();
  assert.equal(currentSnapshot.panes.find((pane) => pane.pane_id === "shell-pane").agent, "claude");
  assert.ok(!currentSnapshot.workspaces.some((workspace) => workspace.workspace_id === "workspace-closed"));
  let state = await reconcile(runtime, api, { now: Date.now() });
  assert.deepEqual(state.recapCoordinator.workspaceDeadlines, {});
  assert.equal(latestSource(await readLatestIndex(runtime.dataRoot), "workspace", "workspace-live"), undefined);

  const piRecap = await publishPi(runtime, {
    sessionId: "pi-live", paneId: "pi-pane", workspaceId: "workspace-live", text: "Pi pane recap",
  });
  state = await reconcile(runtime, api, { now: Date.now() });
  const deadline = state.recapCoordinator.workspaceDeadlines["workspace-live"];
  assert.ok(deadline);
  state = await reconcile(runtime, api, { now: Date.parse(deadline) - 1 });
  assert.equal(state.recapCoordinator.workspaceDeadlines["workspace-live"], deadline);
  assert.equal(
    (await readAllRecapRecords(runtime.dataRoot)).some((record) => record.source_kind === "workspace" && record.source_id === "workspace-live"),
    false,
    "no workspace recap is created before the quiet deadline",
  );

  state = await reconcile(runtime, api, { now: Date.parse(deadline), resumeDeadlines: true });
  assert.equal(state.recapCoordinator.workspaceDeadlines["workspace-live"], undefined);
  const records = await readAllRecapRecords(runtime.dataRoot);
  const liveWorkspace = records.find((record) => record.source_kind === "workspace" && record.source_id === "workspace-live" && record.status === "published");
  const sessionRecap = records.find((record) => record.source_kind === "herdr-session" && record.source_id === "active" && record.status === "published");
  assert.ok(liveWorkspace);
  assert.ok(sessionRecap);
  assert.deepEqual(liveWorkspace.member_record_ids, [currentManual.record_id, piRecap.record_id]);
  assert.ok(!liveWorkspace.member_record_ids.includes(oldManual.record_id), "superseded manual history is retained but not grouped");
  assert.deepEqual(sessionRecap.member_record_ids, [liveWorkspace.record_id]);
  assert.ok(!sessionRecap.member_record_ids.includes(closedWorkspace.record_id), "closed workspace records are excluded from the session group");
  assert.ok(records.some((record) => record.record_id === oldManual.record_id), "older manual recap history remains on disk");
  assert.ok(records.some((record) => record.record_id === closedWorkspace.record_id), "closed workspace history remains on disk");

  const index = await readLatestIndex(runtime.dataRoot);
  assert.equal(latestSource(index, "manual", "shell-pane").latest_success_id, currentManual.record_id);
  assert.equal(latestSource(index, "workspace", "workspace-closed").latest_success_id, closedWorkspace.record_id);
  assert.equal(latestSource(index, "workspace", "workspace-live").latest_success_id, liveWorkspace.record_id);
  assert.equal(latestSource(index, "herdr-session", "active").latest_success_id, sessionRecap.record_id);
  const groupCalls = (await readFile(runtime.captureLog, "utf8")).trim().split("\n")
    .map((line) => JSON.parse(line))
    .filter((call) => call.prompt.startsWith("group:"));
  assert.ok(groupCalls.some((call) => call.prompt.includes("label: Current shell recap")), "the pane-source label reaches the workspace group input");
});

test("a first working Pi prompt follows a rekey even when pane.created precedes pane.moved", async (t) => {
  const runtime = await makeRuntime(t);
  runtime.scheduled = [];
  const api = scriptedHerdrApi({ "old-pi-pane": "workspace-old", "shell-pane": "workspace-new" }, {
    "old-pi-pane": "terminal-pi", "shell-pane": "terminal-shell",
  }, { "old-pi-pane": "pi", "shell-pane": "bash" });
  await reconcile(runtime, api, { now: Date.now() });
  await runtime.runRecap(["prompt", "set", "--session-id", "first-session", "--pane-id", "old-pi-pane"], "First request in progress.\n");
  api.movePane("old-pi-pane", "new-pi-pane", "workspace-new");
  let state = await reconcileOverview({
    ...coordinatorOptions(runtime, api),
    coordinatorWake: false,
    event: { event: "pane.created", data: { pane: { pane_id: "new-pi-pane" } } },
  });
  assert.equal(state.recapCoordinator.piTerminalIdsBySessionId["first-session"], "terminal-pi");
  assert.equal(state.model.panes["new-pi-pane"].prompt.text, "First request in progress.\n");
  assert.equal(state.model.panes["new-pi-pane"].prompt.working, true);
  assert.equal(state.model.panes["old-pi-pane"], undefined);

  // A reconcile while the response is still working must not discard the
  // terminal association just because no successful recap exists yet.
  state = await reconcile(runtime, api, { now: Date.now() });
  assert.equal(state.recapCoordinator.piTerminalIdsBySessionId["first-session"], "terminal-pi");
  assert.equal(state.model.panes["new-pi-pane"].prompt.text, "First request in progress.\n");

  const first = await publishPi(runtime, {
    sessionId: "first-session", paneId: "new-pi-pane", workspaceId: "workspace-new",
  });
  state = await reconcile(runtime, api, { now: Date.now() });
  assert.equal(state.model.panes["new-pi-pane"].recap.latest.record_id, first.record_id);
  const dueAt = Date.parse(state.recapCoordinator.workspaceDeadlines["workspace-new"]);
  state = await reconcile(runtime, api, { now: dueAt });
  const group = (await readAllRecapRecords(runtime.dataRoot)).find((record) => record.source_kind === "workspace"
    && record.source_id === "workspace-new" && record.status === "published");
  assert.deepEqual(group.member_record_ids, [first.record_id]);
});

test("manual pane-source recaps follow live terminal identity across a move and restart", async (t) => {
  const runtime = await makeRuntime(t);
  runtime.scheduled = [];
  let api = scriptedHerdrApi({
    "old-pi-pane": "workspace-old",
    "new-pi-pane": "workspace-new",
    "shell-old-pane": "workspace-old",
  }, {
    "old-pi-pane": "terminal-old-pi",
    "new-pi-pane": "terminal-new-pi",
    "shell-old-pane": "terminal-shell",
  }, { "shell-old-pane": "claude" });

  const manual = await publishManualPane(runtime, "shell-old-pane", {
    label: "Current shell recap",
    text: "A manually published recap for the shell pane.",
  });
  await runtime.setBackendMode("nonzero");
  await assert.rejects(publishManualPane(runtime, "shell-old-pane", { text: "A failed newer manual attempt." }));
  await runtime.setBackendMode("success");
  const orphan = await publishManualPane(runtime, "not-a-live-pane", { text: "Must not be assigned to a native pane." });
  let state = await reconcile(runtime, api, { now: Date.now(), resumeDeadlines: true });
  assert.equal(state.recapCoordinator.manualTerminalIdsBySourceId["shell-old-pane"], "terminal-shell");
  assert.equal(state.recapCoordinator.manualTerminalIdsBySourceId["not-a-live-pane"], undefined);
  assert.equal(state.model.panes["shell-old-pane"].recap.latest.record_id, manual.record_id);
  assert.equal(state.model.panes["shell-old-pane"].recap.lastAttempt.status, "failed");

  const oldPi = await publishPi(runtime, {
    sessionId: "pi-old-workspace", paneId: "old-pi-pane", workspaceId: "workspace-old", text: "Still working in old workspace.",
  });
  const newPi = await publishPi(runtime, {
    sessionId: "pi-new-workspace", paneId: "new-pi-pane", workspaceId: "workspace-new", text: "Work in destination workspace.",
  });
  state = await reconcile(runtime, api, { now: Date.now(), resumeDeadlines: true });
  const oldDeadline = state.recapCoordinator.workspaceDeadlines["workspace-old"];
  const newDeadline = state.recapCoordinator.workspaceDeadlines["workspace-new"];
  assert.ok(oldDeadline && newDeadline);

  api.movePane("shell-old-pane", "shell-new-pane", "workspace-new");
  const movedSnapshot = await api.snapshot();
  assert.equal(movedSnapshot.panes.some((pane) => pane.pane_id === "shell-old-pane"), false);
  assert.equal(movedSnapshot.panes.find((pane) => pane.pane_id === "shell-new-pane").terminal_id, "terminal-shell");
  assert.equal(movedSnapshot.panes.find((pane) => pane.pane_id === "shell-new-pane").agent, "claude");

  // A fresh adapter models server restart: the persisted source-to-terminal
  // association keeps the immutable manual source attached to this live pane.
  api = scriptedHerdrApi(
    Object.fromEntries(movedSnapshot.panes.map((pane) => [pane.pane_id, pane.workspace_id])),
    Object.fromEntries(movedSnapshot.panes.map((pane) => [pane.pane_id, pane.terminal_id])),
    Object.fromEntries(movedSnapshot.panes.map((pane) => [pane.pane_id, pane.agent])),
  );
  state = await reconcileOverview({
    ...coordinatorOptions(runtime, api),
    coordinatorWake: false,
    event: { event: "pane.moved", data: { previous_pane_id: "shell-old-pane", pane: { pane_id: "shell-new-pane" } } },
  });
  assert.equal(state.model.panes["shell-old-pane"], undefined);
  assert.equal(state.model.panes["shell-new-pane"].recap.latest.record_id, manual.record_id);
  assert.equal(state.model.panes["shell-new-pane"].recap.lastAttempt.status, "failed");
  assert.equal(state.recapCoordinator.manualTerminalIdsBySourceId["shell-old-pane"], "terminal-shell");

  const dueAt = Math.max(Date.parse(oldDeadline), Date.parse(newDeadline));
  state = await reconcile(runtime, api, { now: dueAt, resumeDeadlines: true });
  assert.equal(state.recapCoordinator.workspaceDeadlines["workspace-old"], undefined);
  assert.equal(state.recapCoordinator.workspaceDeadlines["workspace-new"], undefined);

  const records = await readAllRecapRecords(runtime.dataRoot);
  const oldWorkspace = records.find((record) => record.source_kind === "workspace"
    && record.source_id === "workspace-old" && record.status === "published");
  const newWorkspace = records.find((record) => record.source_kind === "workspace"
    && record.source_id === "workspace-new" && record.status === "published");
  assert.ok(oldWorkspace && newWorkspace);
  assert.deepEqual(oldWorkspace.member_record_ids, [oldPi.record_id]);
  assert.deepEqual(new Set(newWorkspace.member_record_ids), new Set([manual.record_id, newPi.record_id]));
  assert.ok(!newWorkspace.member_record_ids.includes(orphan.record_id));

  const index = await readLatestIndex(runtime.dataRoot);
  assert.equal(latestSource(index, "workspace", "workspace-old").latest_success_id, oldWorkspace.record_id);
  assert.equal(latestSource(index, "workspace", "workspace-new").latest_success_id, newWorkspace.record_id);
  const activeSessionId = latestSource(index, "herdr-session", "active").latest_success_id;
  const activeSession = records.find((record) => record.record_id === activeSessionId);
  assert.ok(activeSession);
  assert.deepEqual(new Set(activeSession.member_record_ids), new Set([oldWorkspace.record_id, newWorkspace.record_id]));
  assert.ok(records.some((record) => record.record_id === manual.record_id), "the original manual record remains retained");
});

test("restart drains an unprocessed success, resumes its quiet deadline, and publishes current groups once", async (t) => {
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

  // No group is published just before the last publication's quiet deadline.
  await reconcile(runtime, api, { now: Date.parse(deadline) - 1 });
  let records = await readAllRecapRecords(runtime.dataRoot);
  assert.equal(records.filter((record) => record.source_kind === "workspace" && record.status === "published").length, 0);

  // Leave a successful publication unprocessed while the old deadline is pending,
  // then model a server restart with a fresh native API adapter. Startup must
  // catch up the record, reset its publication-time deadline, and resume it once due.
  const unprocessed = await publishPi(runtime, {
    sessionId: "pi-two", paneId: "pane-two", workspaceId: "workspace-a", text: "Pane-two recap published before restart",
  });
  const restartDeadline = new Date(Date.parse(unprocessed.published_at) + 30_000).toISOString();
  const restartedApi = scriptedHerdrApi({ "pane-one": "workspace-a", "pane-two": "workspace-a" });
  state = await reconcile(runtime, restartedApi, { now: Date.parse(restartDeadline), resumeDeadlines: true });
  assert.equal(state.recapCoordinator.workspaceDeadlines["workspace-a"], undefined);
  assert.ok(state.recapCoordinator.processedRecordIds.includes(unprocessed.record_id));
  const processedCount = state.recapCoordinator.processedRecordIds.length;
  state = await reconcile(runtime, restartedApi, { now: Date.parse(restartDeadline), resumeDeadlines: true });
  assert.equal(state.recapCoordinator.processedRecordIds.length, processedCount);

  records = await readAllRecapRecords(runtime.dataRoot);
  const workspacePublished = records.filter((record) => record.source_kind === "workspace" && record.status === "published");
  const sessionPublished = records.filter((record) => record.source_kind === "herdr-session" && record.status === "published");
  assert.equal(workspacePublished.length, 1, "one workspace publication for the recovered quiet window");
  assert.equal(sessionPublished.length, 1, "the session publication follows workspace success exactly once");
  assert.deepEqual(new Set(workspacePublished[0].member_record_ids), new Set([unprocessed.record_id, paneOneLatest.record_id]));
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

test("auto-off suppresses pending group calls and wake-ups until opt-in", async (t) => {
  const runtime = await makeRuntime(t);
  runtime.scheduled = [];
  const api = scriptedHerdrApi({ "pane-one": "workspace-one" });
  const piRecap = await publishPi(runtime, {
    sessionId: "pi-pending", paneId: "pane-one", workspaceId: "workspace-one", text: "Ready for grouping",
  });
  let state = await reconcile(runtime, api, { now: Date.now() });
  const deadline = state.recapCoordinator.workspaceDeadlines["workspace-one"];
  assert.ok(deadline);
  const capturesBefore = (await readFile(runtime.captureLog, "utf8")).trim().split("\n").length;

  await runtime.setAutoPublish(false);
  runtime.scheduled.length = 0;
  state = await reconcile(runtime, api, { now: Date.parse(deadline) - 1, resumeDeadlines: true });
  assert.equal(state.recapCoordinator.workspaceDeadlines["workspace-one"], deadline);
  assert.deepEqual(runtime.scheduled, []);
  state = await reconcile(runtime, api, { now: Date.parse(deadline), resumeDeadlines: true });
  assert.equal(state.recapCoordinator.workspaceDeadlines["workspace-one"], deadline);
  assert.equal(state.model.panes["pane-one"].recap.latest.record_id, piRecap.record_id);
  assert.deepEqual(runtime.scheduled, []);
  assert.equal((await readAllRecapRecords(runtime.dataRoot)).filter((r) =>
    r.source_kind === "workspace" || r.source_kind === "herdr-session").length, 0);
  assert.equal((await readFile(runtime.captureLog, "utf8")).trim().split("\n").length, capturesBefore);

  await runtime.setAutoPublish(true);
  state = await reconcile(runtime, api, { now: Date.parse(deadline), resumeDeadlines: true });
  assert.equal(state.recapCoordinator.workspaceDeadlines["workspace-one"], undefined);
  const groups = (await readAllRecapRecords(runtime.dataRoot)).filter((r) =>
    r.source_kind === "workspace" || r.source_kind === "herdr-session");
  assert.deepEqual(groups.map((r) => r.source_kind).sort(), ["herdr-session", "workspace"]);
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

  await runtime.setBackendMode("blank");
  state = await reconcile(runtime, api, { now: Date.parse(deadline), resumeDeadlines: true });
  assert.equal(state.recapCoordinator.workspaceDeadlines["workspace-failure"], deadline, "a blank group leaves the deadline due");
  let index = await readLatestIndex(runtime.dataRoot);
  let failedWorkspaceSource = latestSource(index, "workspace", "workspace-failure");
  assert.ok(failedWorkspaceSource);
  assert.equal(failedWorkspaceSource.latest_success_id, null);
  assert.equal(latestSource(index, "herdr-session", "active"), undefined);
  let records = await readAllRecapRecords(runtime.dataRoot);
  let failedAttempt = records.find((record) => record.record_id === failedWorkspaceSource.last_attempt_id);
  assert.equal(failedAttempt.status, "failed");
  assert.deepEqual(failedAttempt.member_record_ids, [piRecap.record_id]);
  assert.equal(records.filter((record) => record.source_kind === "herdr-session").length, 0);

  await runtime.setBackendMode("nonzero");
  state = await reconcile(runtime, api, { now: Date.parse(deadline) });
  assert.equal(state.recapCoordinator.workspaceDeadlines["workspace-failure"], deadline, "a command failure also leaves the deadline due");
  index = await readLatestIndex(runtime.dataRoot);
  failedWorkspaceSource = latestSource(index, "workspace", "workspace-failure");
  records = await readAllRecapRecords(runtime.dataRoot);
  failedAttempt = records.find((record) => record.record_id === failedWorkspaceSource.last_attempt_id);
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
