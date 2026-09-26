import path from "node:path";
import { HerdrApi } from "./herdr-api.mjs";
import { normalizeSnapshot } from "./model.mjs";
import { evaluateDisplayNamePolicy, recordDisplayNameWrite } from "./display-name-policy.mjs";
import { readRecapFields, sessionRecapDataRoot } from "./recap-store.mjs";
import { reconcileRecapCoordinator, runSessionRecap } from "./recap-coordinator.mjs";
import { scheduleDeadlineWakeup } from "./deadline-wakeup.mjs";
import { readTheme } from "./theme.mjs";
import { overviewStateDir, readState, withStateLock, writeState } from "./state-store.mjs";

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

function isOverviewProcess(processInfo) {
  return (processInfo?.foreground_processes ?? []).some((process) => {
    const command = [process.argv0, ...(process.argv ?? []), process.cmdline].filter(Boolean).join(" ");
    return /(?:^|[\/\s])index\.mjs(?:\s|$)/.test(command) && /(?:^|\s)overview(?:\s|$)/.test(command);
  });
}

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const SHELL_NAMES = new Set(["bash", "zsh", "sh", "dash", "fish", "nu", "pwsh", "powershell"]);

function isShellOnly(processInfo) {
  const processes = processInfo?.foreground_processes ?? [];
  return processes.length > 0 && processes.every((process) => {
    const name = path.basename(process.name ?? process.argv0 ?? "").toLowerCase();
    return SHELL_NAMES.has(name);
  });
}

async function overviewPaneProcessInfo(api, paneId) {
  let latest = null;
  for (let attempt = 0; attempt < 6; attempt += 1) {
    latest = await tryRead(() => api.processInfo(paneId), null);
    if (isOverviewProcess(latest) || isShellOnly(latest)) return latest;
    if (attempt < 5) await delay(100);
  }
  return latest;
}

async function closeStaleOverviewPane(api, snapshot, paneId, processInfo) {
  const pane = snapshot.panes.find((item) => item.pane_id === paneId);
  const tab = snapshot.tabs.find((item) => item.tab_id === pane?.tab_id);
  const hasSiblingTab = Boolean(pane && snapshot.tabs.some((item) => item.workspace_id === pane.workspace_id && item.tab_id !== pane.tab_id));
  if (tab?.label !== "Herdr Overview" || tab.pane_count !== 1 || !hasSiblingTab || !isShellOnly(processInfo)) return false;
  await api.closePane(paneId);
  return true;
}

export async function reconcileOverview({
  api = new HerdrApi(),
  stateDir = overviewStateDir(),
  dataRoot = sessionRecapDataRoot(),
  configPath = process.env.HERDR_CONFIG_PATH || path.join(process.env.HOME || "", ".config", "herdr", "config.toml"),
  openPane = true,
  event = null,
  resetName = null,
  coordinatorWake = false,
  resumeDeadlines = false,
  coordinatorNow = () => Date.now(),
  recapRunner = runSessionRecap,
  scheduleWakeup = scheduleDeadlineWakeup,
  env = process.env,
} = {}) {
  return withStateLock(stateDir, async () => {
    const previousState = await readState(stateDir);
    let recapCoordinator = previousState.recapCoordinator ?? null;
    let wakeups = [];
    if (coordinatorWake) {
      const result = await reconcileRecapCoordinator({
        state: recapCoordinator,
        dataRoot,
        now: coordinatorNow(),
        runRecap: recapRunner,
        resumeDeadlines,
        persist: async (next) => writeState(stateDir, { ...previousState, recapCoordinator: next }),
      });
      recapCoordinator = result.state;
      wakeups = result.wakeups;
    }
    const previousPanes = previousState.model?.panes ?? {};
    const name = eventName(event);
    const data = eventPayload(event);
    const changedPane = targetPaneId(event, data);
    const snapshotBeforeOpen = await api.snapshot();
    let overviewPaneId = previousState.overviewPaneId ?? null;

    if (overviewPaneId && snapshotBeforeOpen.panes.some((pane) => pane.pane_id === overviewPaneId)) {
      const processInfo = await overviewPaneProcessInfo(api, overviewPaneId);
      if (!isOverviewProcess(processInfo)) {
        await tryRead(() => closeStaleOverviewPane(api, snapshotBeforeOpen, overviewPaneId, processInfo), false);
        overviewPaneId = null;
      }
    } else {
      overviewPaneId = null;
    }
    if (env.HERDR_PLUGIN_ENTRYPOINT_ID === "overview" && snapshotBeforeOpen.panes.some((pane) => pane.pane_id === env.HERDR_PANE_ID)) {
      overviewPaneId = env.HERDR_PANE_ID;
    }

    if (openPane && !overviewPaneId && snapshotBeforeOpen.workspaces.length > 0) {
      const opened = await api.openOverviewPane({ placement: "tab", focus: false });
      const openedPane = opened?.plugin_pane?.pane;
      overviewPaneId = openedPane?.pane_id ?? null;
      if (!overviewPaneId) throw new Error("Herdr did not return the opened overview pane ID");
      if (openedPane.tab_id) await api.renameTab(openedPane.tab_id, "Herdr Overview");
    }

    const snapshot = openPane && !overviewPaneId
      ? await api.snapshot()
      : overviewPaneId && !snapshotBeforeOpen.panes.some((pane) => pane.pane_id === overviewPaneId)
        ? await api.snapshot()
        : snapshotBeforeOpen;
    const excludedPaneIds = overviewPaneId ? [overviewPaneId] : [];
    const moveFromId = name === "pane.moved" ? data.previous_pane_id : null;
    const moveToId = name === "pane.moved" ? data.pane?.pane_id ?? changedPane : null;
    const outputByPaneId = {};
    const processByPaneId = {};

    for (const pane of snapshot.panes) {
      const id = pane.pane_id;
      if (excludedPaneIds.includes(id)) continue;
      const previousId = id === moveToId && moveFromId ? moveFromId : id;
      const previous = previousPanes[previousId];
      const wasTargeted = id === changedPane || previousId === changedPane || id === moveToId;
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

    const supplied = await readRecapFields(snapshot, dataRoot);
    const namingInputs = {
      processByPaneId,
      supplied,
      ownership: previousState.displayNameOwnership,
      resetName,
      excludedPaneIds,
    };
    let namePolicy = evaluateDisplayNamePolicy(snapshot, namingInputs);
    // Pane/output reads can take long enough for an owner to rename a label.
    // Recheck native labels immediately before writing any automatic names.
    if (namePolicy.rename.length) {
      namePolicy = evaluateDisplayNamePolicy(await api.snapshot(), namingInputs);
    }
    for (const update of namePolicy.rename) {
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
      overviewPaneId,
      displayNameOwnership: namePolicy.ownership,
      model,
      theme,
      themeError,
      ...(recapCoordinator ? { recapCoordinator } : {}),
    };
    await writeState(stateDir, state);
    if (coordinatorWake) {
      const socketPath = api.socketPath ?? env.HERDR_SOCKET_PATH;
      for (const wakeup of wakeups) {
        try {
          scheduleWakeup({ stateDir, ...wakeup, socketPath, env });
        } catch (error) {
          console.error(`[herdr-overview] could not schedule recap deadline wake-up: ${error.message}`);
        }
      }
    }
    return state;
  });
}
