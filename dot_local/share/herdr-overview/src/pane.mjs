import { watch } from "node:fs";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { HerdrApi } from "./herdr-api.mjs";
import { sessionRecapDataRoot } from "./recap-store.mjs";
import { overviewStateDir } from "./state-store.mjs";
import { readTheme, watchThemeConfig } from "./theme.mjs";
import { renderBoard } from "./presenters/board.mjs";
import { renderMosaic } from "./presenters/mosaic.mjs";
import {
  backJourneyLevel,
  createJourney,
  getCurrentPaneId,
  movePane,
  moveTab,
  moveWorkspace,
  openJourneyLevel,
  reconcileJourney,
  scrollDetail,
} from "./navigation.mjs";

const MOBILE_WIDTH_THRESHOLD = 64;

export function renderOverview(state, width = process.stdout.columns || 100, height = process.stdout.rows || 24, now = Date.now()) {
  if (!state?.model) return "Herdr Overview is waiting for its first session snapshot.";
  const threshold = state.theme?.mobileWidthThreshold ?? state.theme?.mobile_width_threshold ?? MOBILE_WIDTH_THRESHOLD;
  const screen = width <= threshold
    ? renderBoard(state, width, height, now)
    : renderMosaic(state, width, height, now);
  return state.notice ? `${screen}\n${state.notice}` : screen;
}

async function readState(stateDir) {
  try {
    return JSON.parse(await readFile(path.join(stateDir, "overview.json"), "utf8"));
  } catch {
    return null;
  }
}

function decodeKeys(buffer) {
  const text = buffer.toString("utf8");
  const keys = [];
  for (let index = 0; index < text.length;) {
    if (text[index] === "\u001b") {
      const arrow = text.slice(index).match(/^\u001b\[([ABCD])/);
      if (arrow) {
        keys.push(({ A: "k", B: "j", C: "]", D: "[" })[arrow[1]]);
        index += arrow[0].length;
      } else {
        keys.push("escape");
        index += 1;
      }
      continue;
    }
    const char = text[index++];
    if (char === "\u0003") keys.push("ctrl-c");
    else if (char === "\r" || char === "\n") keys.push("enter");
    else if (char === "\u007f" || char === "\b") keys.push("backspace");
    else keys.push(char);
  }
  return keys;
}

export async function runOverviewPane({
  api = new HerdrApi(),
  stateDir = overviewStateDir(),
  dataRoot = sessionRecapDataRoot(),
  configPath = process.env.HERDR_CONFIG_PATH || path.join(process.env.HOME || "", ".config", "herdr", "config.toml"),
  input = process.stdin,
  output = process.stdout,
  env = process.env,
} = {}) {
  let state = await readState(stateDir) ?? { model: null };
  let journey = state.model ? createJourney(state.model) : null;
  const livePreviews = new Map();
  const retainLivePreviews = (next) => {
    for (const [paneId, text] of livePreviews) {
      if (next.model?.panes?.[paneId]) next.model.panes[paneId].preview = text;
      else livePreviews.delete(paneId);
    }
    return next;
  };
  let theme = state.theme ?? null;
  try { theme = await readTheme(configPath); } catch { /* Theme errors do not hide live panes. */ }
  const draw = () => {
    const screen = renderOverview({ ...state, journey, theme }, output.columns || 100, output.rows || 24);
    if (output.isTTY) output.write("\u001b[2J\u001b[H");
    output.write(`${screen}\n`);
  };
  draw();
  if (!input.isTTY || !input.setRawMode) return;

  input.setRawMode(true);
  input.resume();
  const statePath = path.join(stateDir, "overview.json");
  let outputSubscription = null;
  let subscribedPaneIds = "";
  let cleaned = false;
  const syncOutputSubscription = async () => {
    const paneIds = Object.keys(state?.model?.panes ?? {}).sort();
    const key = paneIds.join("\n");
    if (key === subscribedPaneIds) return;
    outputSubscription?.close();
    outputSubscription = null;
    subscribedPaneIds = "";
    if (paneIds.length) {
      outputSubscription = await api.subscribe(paneIds.map((paneId) => ({
        type: "pane.output_matched",
        pane_id: paneId,
        source: "recent_unwrapped",
        lines: 12,
        match: { type: "regex", value: ".+" },
        strip_ansi: true,
      })), (event) => {
        // Output events already contain recent text. Keep the open view current
        // without running full, lock-held reconciliation for every output line.
        const data = event?.data ?? event;
        const paneId = data?.pane_id;
        const text = data?.read?.text;
        if (typeof text !== "string" || !state.model?.panes?.[paneId]) return;
        livePreviews.set(paneId, text);
        state.model.panes[paneId].preview = text;
        draw();
      }, (error) => output.write(`\nOutput subscription failed: ${error.message}\n`));
    }
    subscribedPaneIds = key;
  };
  const stateWatcher = watch(stateDir, (_event, changed) => {
    if (changed && changed.toString() !== path.basename(statePath)) return;
    readState(stateDir).then(async (next) => {
      if (!next) return;
      state = retainLivePreviews(next);
      journey = reconcileJourney(journey, state.model);
      draw();
      try { await syncOutputSubscription(); }
      catch (error) { output.write(`\nOutput subscription failed: ${error.message}\n`); }
    }).catch(() => {});
  });
  const stopThemeWatch = watchThemeConfig(configPath, (nextTheme) => {
    if (nextTheme) theme = nextTheme;
    draw();
  });
  try { await syncOutputSubscription(); }
  catch (error) { output.write(`\nOutput subscription failed: ${error.message}\n`); }

  let onKey;
  const cleanup = () => {
    if (cleaned) return;
    cleaned = true;
    stateWatcher.close();
    stopThemeWatch();
    outputSubscription?.close();
    input.off?.("data", onKey);
    if (input.isTTY && input.isRaw) input.setRawMode(false);
    input.pause();
  };
  await new Promise((resolve, reject) => {
    const focus = async () => {
      const paneId = state.model && getCurrentPaneId(journey, state.model);
      if (!paneId) return;
      try {
        await api.focusPane(paneId);
        state.notice = `Focused native Herdr pane ${paneId}.`;
      } catch (error) {
        state.notice = `Could not focus native pane ${paneId}: ${error.message}`;
      }
      draw();
    };
    const handleKey = async (key) => {
      if (key === "q" || key === "ctrl-c") { cleanup(); resolve(); return; }
      if (state.notice) state.notice = null;
      if (!state.model) return;
      if (key === "r") {
        state = retainLivePreviews(await readState(stateDir) ?? state);
        journey = reconcileJourney(journey, state.model);
        draw();
        return;
      }
      if (key === "escape" || key === "backspace") {
        journey = backJourneyLevel(journey);
        draw();
        return;
      }
      if (key === "f") { await focus(); return; }
      if (key === "enter") {
        if (journey.level === "pane") await focus();
        else { journey = openJourneyLevel(journey, state.model); draw(); }
        return;
      }
      if (key === "j" || key === "\u001b[B") {
        if (journey.level === "overview") journey = moveWorkspace(journey, state.model, 1);
        else if (journey.level === "workspace") journey = movePane(journey, state.model, 1);
        else journey = scrollDetail(journey, 1);
        draw();
        return;
      }
      if (key === "k" || key === "\u001b[A") {
        if (journey.level === "overview") journey = moveWorkspace(journey, state.model, -1);
        else if (journey.level === "workspace") journey = movePane(journey, state.model, -1);
        else journey = scrollDetail(journey, -1);
        draw();
        return;
      }
      if ((key === "[" || key === "]") && journey.level === "workspace") {
        journey = moveTab(journey, state.model, key === "]" ? 1 : -1);
        draw();
        return;
      }
      if (key === " " || key === "b") {
        if (journey.level === "pane") journey = scrollDetail(journey, key === " " ? Math.max(1, (output.rows || 24) - 6) : -Math.max(1, (output.rows || 24) - 6));
        draw();
      }
    };
    onKey = async (buffer) => {
      for (const key of decodeKeys(buffer)) await handleKey(key);
    };
    input.on("data", onKey);
    input.once("error", (error) => { cleanup(); reject(error); });
    input.once("end", () => { cleanup(); resolve(); });
  });
  cleanup();
}
