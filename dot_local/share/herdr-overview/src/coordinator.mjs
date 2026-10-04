import path from "node:path";
import { HerdrApi } from "./herdr-api.mjs";
import { normalizeSnapshot } from "./model.mjs";
import { confirmDisplayNameWrite, evaluateDisplayNamePolicy, recordDisplayNameWrite } from "./display-name-policy.mjs";
import { readRecapFields, sessionRecapDataRoot } from "./recap-store.mjs";
import { readPiSessionFields } from "./pi-session-store.mjs";
import { applyCompletedGroups, autoPublishEnabled, planRecapCoordinator, runDueGroups, runSessionRecap } from "./recap-coordinator.mjs";
import { scheduleDeadlineWakeup } from "./deadline-wakeup.mjs";
import { readTheme } from "./theme.mjs";
import { overviewStateDir, readState, withGroupLock, withStateLock, writeState } from "./state-store.mjs";

function eventPayload(event) {
  if (!event || typeof event !== "object") return {};
  return event.data && typeof event.data === "object" ? event.data : event;
}

function eventName(event) {
  return String(event?.event ?? event?.type ?? "").replace(/^([a-z]+)_/, "$1.");
}

function targetPaneId(event, data) {
  return data.pane_id ?? data.pane?.pane_id ?? null;
}

async function tryRead(callback, fallback) {
  try {
    return await callback();
  } catch {
    return fallback;
  }
}

// Group generation calls the summary model. It runs between two short
// state-lock passes so event hooks and the popup never wait on the model.
export async function reconcileOverview(options = {}) {
  const {
    api = new HerdrApi(),
    stateDir = overviewStateDir(),
    dataRoot = sessionRecapDataRoot(),
    coordinatorWake = false,
    recapRunner = runSessionRecap,
    scheduleWakeup = scheduleDeadlineWakeup,
    env = process.env,
  } = options;
  const run = { ...options, api, stateDir, dataRoot };
  let result = await withStateLock(stateDir, () => refreshOverview(run));
  if (!coordinatorWake) return result.state;

  const firstPlan = result.plan;
  const enabled = (firstPlan.due.length || firstPlan.wakeups.length) && await autoPublishEnabled(recapRunner);
  if (enabled && firstPlan.due.length) {
    // Each workspace gets one attempt per run; a failure stays due for a later wake-up.
    const attempted = new Set();
    // If another process holds the group lock, it rechecks due work before it stops.
    await withGroupLock(stateDir, async () => {
      for (;;) {
        const due = result.plan.due.filter(({ workspaceId }) => !attempted.has(workspaceId));
        if (!due.length) return;
        for (const { workspaceId } of due) attempted.add(workspaceId);
        const completed = await runDueGroups({
          due, state: result.state.recapCoordinator, dataRoot, snapshot: result.snapshot, runRecap: recapRunner,
        });
        result = await withStateLock(stateDir, () => refreshOverview({ ...run, completedGroups: completed }));
      }
    });
  }
  if (enabled) {
    const socketPath = api.socketPath ?? env.HERDR_SOCKET_PATH;
    for (const wakeup of firstPlan.wakeups) {
      try {
        scheduleWakeup({ stateDir, ...wakeup, socketPath, env });
      } catch (error) {
        console.error(`[herdr-overview] could not schedule recap deadline wake-up: ${error.message}`);
      }
    }
  }
  return result.state;
}

// One locked pass: native snapshot, recap bookkeeping, naming, model, state write.
async function refreshOverview({
  api,
  stateDir,
  dataRoot,
  configPath = process.env.HERDR_CONFIG_PATH || path.join(process.env.HOME || "", ".config", "herdr", "config.toml"),
  event = null,
  resetName = null,
  coordinatorWake = false,
  resumeDeadlines = false,
  coordinatorNow = () => Date.now(),
  completedGroups = null,
  env = process.env,
}) {
    const previousState = await readState(stateDir);
    const snapshotBeforeOpen = await api.snapshot();
    let recapCoordinator = previousState.recapCoordinator ?? null;
    let plan = null;
    if (coordinatorWake) {
      if (completedGroups) recapCoordinator = applyCompletedGroups(recapCoordinator, completedGroups);
      plan = await planRecapCoordinator({
        state: recapCoordinator,
        dataRoot,
        snapshot: snapshotBeforeOpen,
        now: coordinatorNow(),
        resumeDeadlines,
      });
      recapCoordinator = plan.state;
    }
    const previousPanes = previousState.model?.panes ?? {};
    const name = eventName(event);
    const data = eventPayload(event);
    const changedPane = targetPaneId(event, data);
    // A popup has no native pane identity. Legacy tabs belong to the owner.
    const snapshot = snapshotBeforeOpen;
    const excludedPaneIds = [];
    const currentIds = new Set(snapshot.panes.map((pane) => pane.pane_id));
    const lostByTerminal = new Map();
    for (const [previousPaneId, previous] of Object.entries(previousPanes)) {
      if (currentIds.has(previousPaneId) || previousPaneId === previousState.overviewPaneId || !previous.terminalId) continue;
      const lost = lostByTerminal.get(previous.terminalId) ?? [];
      lost.push(previousPaneId);
      lostByTerminal.set(previous.terminalId, lost);
    }
    // Herdr may emit pane.created before pane.moved. Detect a rekey from the
    // unique live terminal identity, not from event ordering or UI focus.
    const rekeys = snapshot.panes.flatMap((pane) => {
      const matches = lostByTerminal.get(pane.terminal_id) ?? [];
      if (excludedPaneIds.includes(pane.pane_id) || previousPanes[pane.pane_id]
        || matches.length !== 1
        || snapshot.panes.filter((item) => item.terminal_id === pane.terminal_id).length !== 1) return [];
      return [{ previousPaneId: matches[0], paneId: pane.pane_id, terminalId: pane.terminal_id }];
    });
    const previousIdByCurrentId = new Map(rekeys.map((rekey) => [rekey.paneId, rekey.previousPaneId]));
    const outputByPaneId = {};
    const processByPaneId = {};

    for (const pane of snapshot.panes) {
      const id = pane.pane_id;
      if (excludedPaneIds.includes(id)) continue;
      const previousId = previousIdByCurrentId.get(id) ?? id;
      const previous = previousPanes[previousId];
      const wasTargeted = id === changedPane || previousId === changedPane || previousId !== id;
      if (name === "pane.output_matched" && id === changedPane && typeof data.read?.text === "string") {
        outputByPaneId[id] = data.read.text;
        processByPaneId[id] = previous?.processInfo ?? null;
        continue;
      }
      const shouldRead = !previous || wasTargeted && ["pane.created", "pane.moved", "pane.output_changed", "pane.updated", "pane.exited"].includes(name);
      if (shouldRead) {
        outputByPaneId[id] = await tryRead(() => api.readPane(id, { lines: 12 }), previous?.preview ?? null);
        processByPaneId[id] = await tryRead(() => api.processInfo(id), previous?.processInfo ?? null);
      } else {
        if (previous && Object.hasOwn(previous, "preview")) outputByPaneId[id] = previous.preview;
        if (previous && Object.hasOwn(previous, "processInfo")) processByPaneId[id] = previous.processInfo;
      }
    }

    const sessionFields = readPiSessionFields(snapshot, { socketPath: api.socketPath ?? env.HERDR_SOCKET_PATH, env });
    const piTerminalIds = { ...(recapCoordinator?.piTerminalIdsBySessionId ?? {}) };
    for (const pane of snapshot.panes) {
      const session = sessionFields.piSessionsByPaneId[pane.pane_id];
      if (session) piTerminalIds[session.sessionId] = pane.terminal_id;
    }
    const supplied = await readRecapFields(
      snapshot,
      dataRoot,
      piTerminalIds,
      recapCoordinator?.manualTerminalIdsBySourceId,
      rekeys,
    );
    Object.assign(supplied, sessionFields);
    if (rekeys.length || Object.keys(piTerminalIds).length) {
      recapCoordinator = { ...(recapCoordinator ?? {}), piTerminalIdsBySessionId: supplied.piTerminalIdsBySessionId };
    }
    const ownership = { ...(previousState.displayNameOwnership ?? {}) };
    for (const { previousPaneId, paneId } of rekeys) {
      const fromKey = `pane:${previousPaneId}`;
      const toKey = `pane:${paneId}`;
      if (Object.hasOwn(ownership, fromKey) && !Object.hasOwn(ownership, toKey)) {
        ownership[toKey] = ownership[fromKey];
        delete ownership[fromKey];
      }
    }
    const namingInputs = {
      processByPaneId,
      supplied,
      ownership,
      resetName,
      excludedPaneIds,
    };
    let namePolicy = evaluateDisplayNamePolicy(snapshot, namingInputs);
    // Refresh after potentially slow pane reads, then confirm each queued
    // target again immediately before its automatic rename.
    if (namePolicy.rename.length) {
      namePolicy = evaluateDisplayNamePolicy(await api.snapshot(), namingInputs);
    }
    for (const update of namePolicy.rename) {
      const liveSnapshot = await api.snapshot();
      if (!confirmDisplayNameWrite(namePolicy, liveSnapshot, update)) continue;
      // Herdr protocol 22 has no conditional rename. An owner edit between
      // this snapshot and the write can still race; no client fork is implied.
      try {
        if (update.kind === "pane") await api.renamePane(update.id, update.label);
        else await api.renameTab(update.id, update.label);
        recordDisplayNameWrite(namePolicy, update);
      } catch {
        // A failed rename remains automatic and is retried on the next reconciliation.
      }
    }
    const reconciledSnapshot = namePolicy.snapshot;
    const model = normalizeSnapshot(reconciledSnapshot, supplied, {
      previousPanes,
      outputByPaneId,
      processByPaneId,
      excludedPaneIds,
      displayNameOwnership: namePolicy.ownership,
    });
    let theme = null;
    let themeError = null;
    try {
      theme = await readTheme(configPath);
    } catch (error) {
      themeError = error.message;
    }
    const state = {
      schema_version: 1,
      generated_at: new Date().toISOString(),
      displayNameOwnership: namePolicy.ownership,
      model,
      theme,
      themeError,
      ...(recapCoordinator ? { recapCoordinator } : {}),
    };
    await writeState(stateDir, state);
    return { state, plan, snapshot: snapshotBeforeOpen };
}
