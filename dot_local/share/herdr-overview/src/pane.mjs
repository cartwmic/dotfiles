import { watch } from 'node:fs';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { HerdrApi } from './herdr-api.mjs';
import { normalizeSnapshot } from './model.mjs';
import { readRecapFields, sessionRecapDataRoot } from './recap-store.mjs';
import { readPiSessionFields } from './pi-session-store.mjs';
import { overviewStateDir } from './state-store.mjs';
import { readTheme, watchThemeConfig } from './theme.mjs';
import { renderMap, mapFrame } from './presenters/map.mjs';
import { reconcileJourney, getCurrentPaneId, movePane, nextBlocked, openJourneyLevel, backJourneyLevel, scrollDetail, scrollOverview, moveDirection, select } from './navigation.mjs';
export function renderOverview(state, width = 100, height = 24, now = Date.now()) {
  return state?.model ? renderMap(state, width, height, now) : 'Herdr Overview is waiting for its first session snapshot.';
}
async function readState(directory) { try { return JSON.parse(await readFile(path.join(directory, 'overview.json'), 'utf8')); } catch { return null; } }
import { InputDecoder, hitPane } from './input.mjs';
export function decodeKeys(buffer) {
  const decoder = new InputDecoder(); return [...decoder.push(buffer), ...decoder.flush()];
}

export async function runOverviewPane({ api = new HerdrApi(), stateDir = overviewStateDir(), dataRoot = sessionRecapDataRoot(), configPath = process.env.HERDR_CONFIG_PATH || path.join(process.env.HOME || '', '.config/herdr/config.toml'), input = process.stdin, output = process.stdout, env = process.env } = {}) {
  let state = await readState(stateDir) ?? { model: null };
  // Entry follows the current native selection, not a saved viewer selection.
  let journey = null;
  let theme = state.theme;
  let frame, escapeTimer; const decoder = new InputDecoder();
  let closed = false, queue = Promise.resolve();
  try { theme = await readTheme(configPath); } catch {}
  const draw = () => { if (closed) return; if (output.isTTY) output.write('\x1b[2J\x1b[H'); frame = state.model ? mapFrame({ ...state, journey, theme }, output.columns || 100, output.rows || 24) : null; output.write((frame?.text || renderOverview({ ...state, journey, theme })) + (output.isTTY ? '' : '\n')); };
  const refresh = async () => {
    const saved = await readState(stateDir);
    if (saved) state = saved;
    try {
      const snapshot = await api.snapshot();
      const sessions = readPiSessionFields(snapshot, { socketPath: api.socketPath ?? env.HERDR_SOCKET_PATH, env });
      const piTerminals = { ...(state.recapCoordinator?.piTerminalIdsBySessionId ?? {}) };
      const previousPanes = { ...(state.model?.panes ?? {}) };
      const rekeys = [];
      for (const pane of snapshot.panes) {
        const session = sessions.piSessionsByPaneId[pane.pane_id];
        if (session) piTerminals[session.sessionId] = pane.terminal_id;
        const matches = Object.values(state.model?.panes ?? {}).filter(old => old.terminalId && old.terminalId === pane.terminal_id);
        if (matches.length === 1 && snapshot.panes.filter(other => other.terminal_id === pane.terminal_id).length === 1 && !previousPanes[pane.pane_id]) {
          const old = matches[0];
          previousPanes[pane.pane_id] = old;
          rekeys.push({ previousPaneId: old.id, paneId: pane.pane_id, terminalId: pane.terminal_id });
        }
      }
      const supplied = await readRecapFields(snapshot, dataRoot, piTerminals, state.recapCoordinator?.manualTerminalIdsBySourceId, rekeys);
      Object.assign(supplied, sessions);
      state = { ...state, model: normalizeSnapshot(snapshot, supplied, { previousPanes, displayNameOwnership: state.displayNameOwnership, processByPaneId: Object.fromEntries(Object.entries(previousPanes).map(([id, pane]) => [id, pane.processInfo])) }) };
      state.notice = null;
    } catch (error) { state.notice = `Native refresh unavailable: ${error.message}`;
      if (state.model) journey = reconcileJourney(journey, state.model);
      draw(); return false;
    }
    if (state.model) journey = reconcileJourney(journey, state.model);
    draw(); return true;
  };
  await refresh();
  if (!input.isTTY || !input.setRawMode) return;
  const wasRaw = input.isRaw;
  input.setRawMode(true); input.resume();
  try { output.write("\x1b[?1000h\x1b[?1006h"); } catch(error) { input.setRawMode(Boolean(wasRaw)); input.pause(); throw error; }
  let watcher, stopThemeWatch, onKey, onEnd, onError;
  const onResize = () => { if(journey)journey.ensureVisible=true; draw(); };
  const enqueue = callback => { queue = queue.then(async () => { if (!closed) await callback(); }).catch(error => { state.notice = error.message; try { draw(); } catch { onError?.(error); } }); return queue; };
  const cleanup = () => {
    if (closed) return; closed = true;
    clearTimeout(escapeTimer); try { output.write("\x1b[?1006l\x1b[?1000l"); } catch {}
    process.off('SIGTERM',onEnd); process.off('SIGHUP',onEnd);
    watcher?.close(); stopThemeWatch?.();
    output.off?.('resize', onResize); output.off?.('error',onError); input.off('data', onKey); input.off('end', onEnd); input.off('error', onError);
    if (input.isRaw !== wasRaw) input.setRawMode(Boolean(wasRaw)); input.pause();
  };
  await new Promise((resolve, reject) => {
    const dismiss = () => { cleanup(); resolve(); };
    const handle = async key => {
      if (typeof key === 'object') {
        if (!state.model || !journey) return;
        const v=frame?.viewport; if(!v || key.x<0 || key.x>=v.width || key.y<v.y || key.y>=v.y+v.height)return;
        if (key.type === 'wheel') journey = journey.level === 'overview' ? scrollOverview(journey,key.delta) : scrollDetail(journey,key.delta);
        else if (journey.level === 'overview') { const id=hitPane(frame,key.x,key.y); if(id && state.model.panes[id]) journey=select(journey,state.model,id); }
        draw(); return;
      }
      if (key === 'q') return dismiss();
      state.notice = null;
      if (key === 'r') return refresh();
      if (!state.model || !journey) return;
      if (key === 'escape') { if (journey.level === 'overview') return dismiss(); journey = backJourneyLevel(journey); }
      else if (key === 'f') {
        // Resolve against a fresh native snapshot immediately before focus.
        const expected = journey.terminalId;
        if (!await refresh()) return;
        const id = getCurrentPaneId(journey, state.model);
        if (!id || !expected || state.model.panes[id]?.terminalId !== expected) state.notice = 'Cannot focus: selected terminal vanished or identity conflicts.';
        else {
          try { await api.focusPane(id); return dismiss(); }
          catch (error) { state.notice = `Could not focus ${id}: ${error.message}`; }
        }
      }
      else if (key === '[' || key === ']') journey = movePane(journey, state.model, key === '[' ? -1 : 1);
      else if (key === 'n') journey = nextBlocked(journey, state.model);
      else if (key === 'enter') journey = openJourneyLevel(journey);
      else if (key === 'd' && journey.level !== 'digest') journey = { ...journey, returnReading: { detailScroll: journey.detailScroll, readingPosition: journey.readingPosition }, level: 'digest', detailScroll: 0, readingPosition: null };
      else if ('hjkl'.includes(key)) journey = journey.level === 'overview' ? moveDirection(journey, state.model, frame?.rectangles || [], key) : key === 'j' || key === 'k' ? scrollDetail(journey, key === 'j' ? 1 : -1) : journey;
      else if (key === ' ' || key === 'b') journey = (journey.level === 'overview' ? scrollOverview : scrollDetail)(journey, (key === ' ' ? 1 : -1) * Math.max(1, (output.rows || 24) - 3));
      draw();
    };
    const dispatch = keys => enqueue(async () => { for (const key of keys) { if (closed) break; await handle(key); } });
    onKey = buffer => { clearTimeout(escapeTimer); dispatch(decoder.push(buffer)); if(decoder.pending === '\x1b') escapeTimer=setTimeout(()=>dispatch(decoder.flush()),50); };
    process.once('SIGTERM',dismiss); process.once('SIGHUP',dismiss);
    onEnd = dismiss; onError = error => { cleanup(); reject(error); };
    input.on('data', onKey); input.on('end', onEnd); input.on('error', onError); output.on?.('resize', onResize); output.on?.('error',onError);
    try { watcher = watch(stateDir, (_event, name) => { if (!name || name.toString() === 'overview.json') enqueue(refresh); }); } catch {}
    try { stopThemeWatch = watchThemeConfig(configPath, next => { if (next) theme = next; draw(); }); } catch { /* Missing config must not prevent dismissal. */ }
    // Native event hooks publish saved state; reload it without terminal-tail reads.
    // Explicit r also covers events missed while hooks were unavailable.
  });
  cleanup();
}
