// Display order inside a workspace: questions (blocked), then ready, then
// working, then everything else; native order breaks ties.
const RANK = { blocked: 0, idle: 1, working: 2 };
export const paneRank = pane => pane?.agent?.recognized ? RANK[pane.agent.status] ?? 3 : 3;
const byRank = (ids, rank) => ids.map((id, index) => ({ id, index, rank: rank(id) })).sort((a, b) => a.rank - b.rank || a.index - b.index).map(item => item.id);
export function orderedPanesOfTab(model, tabId) {
  return byRank((model.tabs[tabId]?.paneIds ?? []).filter(id => model.panes[id]), id => paneRank(model.panes[id]));
}
export function orderedTabIds(model, workspaceId) {
  return byRank((model.workspaces[workspaceId]?.tabIds ?? []).filter(id => model.tabs[id]), id => Math.min(3, ...orderedPanesOfTab(model, id).map(pane => paneRank(model.panes[pane]))));
}
export function orderedPaneIds(model) {
  return (model.workspaceOrder ?? []).flatMap(id => orderedTabIds(model, id).flatMap(tab => orderedPanesOfTab(model, tab)));
}
export function select(journey, model, id) {
  const pane = model.panes[id];
  return { ...journey, ensureVisible: true, paneId: id ?? null, terminalId: pane?.terminalId ?? null, workspaceId: pane?.workspaceId ?? null, tabId: pane?.tabId ?? null, detailScroll: 0, readingPosition: null, scrollDelta: 0 };
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
export function openJourneyLevel(journey) { return { ...journey, ensureVisible: true, level: journey.level === 'overview' ? 'pane' : 'overview', detailScroll: 0, readingPosition: null, scrollDelta: 0 }; }
export function backJourneyLevel(journey) { return { ...journey, ensureVisible: true, level: journey.level === 'digest' ? 'pane' : 'overview', detailScroll: 0, readingPosition: null, scrollDelta: 0, ...(journey.level === 'digest' ? journey.returnReading : {}) }; }
export function scrollDetail(journey, delta) { return { ...journey, detailScroll: Math.max(0, (journey.detailScroll ?? 0) + delta), scrollDelta: (journey.scrollDelta || 0) + delta }; }

export function scrollOverview(journey, delta) { return { ...journey, overviewScroll: Math.max(0, (journey.overviewScroll || 0) + delta), ensureVisible: false }; }
export function moveDirection(journey, model, rectangles, direction) {
  const current = rectangles.find(r => r.paneId === journey.paneId);
  if (!current) return journey;
  const horizontal = direction === 'h' || direction === 'l', sign = direction === 'h' || direction === 'k' ? -1 : 1;
  const axis = horizontal ? 'x' : 'y', cross = horizontal ? 'y' : 'x', size = horizontal ? 'width' : 'height', span = horizontal ? 'height' : 'width';
  const center = (r,a,z) => r[a]+r[z]/2;
  const candidates = rectangles.filter(r => r.paneId !== current.paneId && model.panes[r.paneId]).map((r,index) => {
    const distance = sign*(center(r,axis,size)-center(current,axis,size)), perpendicular = Math.abs(center(r,cross,span)-center(current,cross,span));
    const overlap = r[cross] < current[cross]+current[span] && current[cross] < r[cross]+r[span];
    const gap = Math.max(0, sign > 0 ? r[axis]-current[axis]-current[size] : current[axis]-r[axis]-r[size]);
    return {r,index,distance,perpendicular,overlap,gap};
  }).filter(c=>c.distance>0);
  const aligned = candidates.filter(c=>c.overlap), choices=aligned.length ? aligned : candidates;
  choices.sort((a,b)=> aligned.length ? a.gap-b.gap || a.perpendicular-b.perpendicular || a.index-b.index : a.perpendicular/a.distance-b.perpendicular/b.distance || Math.hypot(a.distance,a.perpendicular)-Math.hypot(b.distance,b.perpendicular) || a.index-b.index);
  return choices.length ? select(journey,model,choices[0].r.paneId) : {...journey,ensureVisible:true};
}
