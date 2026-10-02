export function orderedPaneIds(model) {
  return (model.workspaceOrder ?? []).flatMap(id => (model.workspaces[id]?.tabIds ?? []).flatMap(tab => model.tabs[tab]?.paneIds ?? [])).filter(id => model.panes[id]);
}
function select(journey, model, id) {
  const pane = model.panes[id];
  return { ...journey, paneId: id ?? null, terminalId: pane?.terminalId ?? null, workspaceId: pane?.workspaceId ?? null, tabId: pane?.tabId ?? null, detailScroll: 0, readingPosition: null, scrollDelta: 0 };
}
export function createJourney(model) {
  return select({ level: 'overview', detailScroll: 0 }, model, model.panes[model.selection?.paneId] ? model.selection.paneId : orderedPaneIds(model)[0]);
}
export function reconcileJourney(journey, model) {
  if (!journey) return createJourney(model);
  const matches = Object.values(model.panes).filter(pane => pane.terminalId && pane.terminalId === journey.terminalId);
  const same = model.panes[journey.paneId];
  const pane = journey.terminalId ? (matches.length === 1 ? matches[0] : null) : same;
  if (!pane || (same && journey.terminalId && same.terminalId !== journey.terminalId)) return { ...journey, paneId: null };
  return { ...journey, paneId: pane.id, workspaceId: pane.workspaceId, tabId: pane.tabId };
}
export function getCurrentPaneId(journey, model) {
  const current = reconcileJourney(journey, model);
  return current.paneId ?? null;
}
export function movePane(journey, model, delta) {
  const ids = orderedPaneIds(model);
  if (!ids.length) return journey;
  const index = ids.indexOf(journey.paneId);
  return select(journey, model, ids[(Math.max(0, index) + delta + ids.length) % ids.length]);
}
export const moveTab = movePane;
export const moveWorkspace = movePane;
export function nextBlocked(journey, model) {
  const ids = orderedPaneIds(model);
  const start = ids.indexOf(journey.paneId);
  for (let step = 1; step <= ids.length; step++) {
    const id = ids[(start + step + ids.length) % ids.length];
    if (model.panes[id].agent?.status === 'blocked') return select(journey, model, id);
  }
  return journey;
}
export function openJourneyLevel(journey) { return { ...journey, level: journey.level === 'overview' ? 'pane' : 'overview', detailScroll: 0, readingPosition: null, scrollDelta: 0 }; }
export function backJourneyLevel(journey) { return { ...journey, level: journey.level === 'digest' ? 'pane' : 'overview', detailScroll: 0, readingPosition: null, scrollDelta: 0, ...(journey.level === 'digest' ? journey.returnReading : {}) }; }
export function scrollDetail(journey, delta) { return { ...journey, detailScroll: Math.max(0, (journey.detailScroll ?? 0) + delta), scrollDelta: (journey.scrollDelta || 0) + delta }; }
