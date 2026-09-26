function workspaceIds(model) {
  return model.workspaceOrder.filter((id) => model.workspaces[id]);
}

function paneIds(model, workspaceId) {
  const workspace = model.workspaces[workspaceId];
  if (!workspace) return [];
  return workspace.tabIds.flatMap((tabId) => model.tabs[tabId]?.paneIds ?? []).filter((id) => model.panes[id]);
}

function firstPaneFor(model, workspaceId, tabId = null) {
  const workspace = model.workspaces[workspaceId];
  const tabIds = tabId && workspace?.tabIds.includes(tabId) ? [tabId] : workspace?.tabIds ?? [];
  for (const id of tabIds) {
    const paneId = model.tabs[id]?.paneIds.find((candidate) => model.panes[candidate]);
    if (paneId) return { tabId: id, paneId };
  }
  return { tabId: tabIds[0] ?? null, paneId: null };
}

function selectionInWorkspace(model, workspaceId, paneId) {
  if (paneId && model.panes[paneId]?.workspaceId === workspaceId) {
    return { tabId: model.panes[paneId].tabId, paneId };
  }
  const workspace = model.workspaces[workspaceId];
  return firstPaneFor(model, workspaceId, workspace?.activeTabId);
}

export function createJourney(model) {
  const ids = workspaceIds(model);
  const selectedPane = model.selection?.paneId ? model.panes[model.selection.paneId] : null;
  const workspaceId = ids.includes(model.selection?.workspaceId)
    ? model.selection.workspaceId
    : selectedPane?.workspaceId ?? ids[0] ?? null;
  const selection = selectionInWorkspace(model, workspaceId, model.selection?.paneId);
  const nativeTabId = model.selection?.tabId;
  if (!model.tabs[selection.tabId] && model.tabs[nativeTabId]?.workspaceId === workspaceId) selection.tabId = nativeTabId;
  return { level: "overview", workspaceId, ...selection, detailScroll: 0 };
}

export function reconcileJourney(journey, model) {
  const ids = workspaceIds(model);
  if (!ids.length) return { level: "overview", workspaceId: null, tabId: null, paneId: null, detailScroll: 0 };
  let workspaceId = ids.includes(journey?.workspaceId) ? journey.workspaceId : null;
  const survivingPane = model.panes[journey?.paneId];
  if (survivingPane && ids.includes(survivingPane.workspaceId)) workspaceId = survivingPane.workspaceId;
  if (!workspaceId) workspaceId = ids[0];
  let selection;
  if (journey?.tabId && model.tabs[journey.tabId]?.workspaceId === workspaceId) {
    const tab = model.tabs[journey.tabId];
    const paneId = tab.paneIds.includes(journey.paneId) ? journey.paneId : tab.paneIds.find((id) => model.panes[id]) ?? null;
    selection = { tabId: tab.id, paneId };
  } else {
    selection = selectionInWorkspace(model, workspaceId, journey?.paneId);
  }
  const level = journey?.level === "workspace" || journey?.level === "pane" ? journey.level : "overview";
  if (level === "pane" && !selection.paneId) return { level: "workspace", workspaceId, ...selection, detailScroll: 0 };
  return {
    level,
    workspaceId,
    ...selection,
    detailScroll: Number.isInteger(journey?.detailScroll) && journey.detailScroll > 0 ? journey.detailScroll : 0,
  };
}

export function getCurrentPaneId(journey, model) {
  const selected = model.panes[journey?.paneId];
  if (selected && selected.workspaceId === journey.workspaceId) return selected.id;
  const native = model.panes[model.selection?.paneId];
  if (native && native.workspaceId === journey.workspaceId) return native.id;
  return paneIds(model, journey?.workspaceId)[0] ?? null;
}

export function moveWorkspace(journey, model, delta) {
  const ids = workspaceIds(model);
  if (!ids.length) return journey;
  const current = Math.max(0, ids.indexOf(journey.workspaceId));
  const workspaceId = ids[(current + delta + ids.length) % ids.length];
  return { ...journey, workspaceId, ...selectionInWorkspace(model, workspaceId, null), detailScroll: 0 };
}

export function movePane(journey, model, delta) {
  const ids = paneIds(model, journey.workspaceId);
  if (!ids.length) return journey;
  const current = Math.max(0, ids.indexOf(journey.paneId));
  const paneId = ids[(current + delta + ids.length) % ids.length];
  const pane = model.panes[paneId];
  return { ...journey, tabId: pane.tabId, paneId, detailScroll: 0 };
}

export function moveTab(journey, model, delta) {
  const tabs = model.workspaces[journey.workspaceId]?.tabIds.filter((id) => model.tabs[id]) ?? [];
  if (!tabs.length) return journey;
  const current = Math.max(0, tabs.indexOf(journey.tabId));
  const tabId = tabs[(current + delta + tabs.length) % tabs.length];
  const paneId = model.tabs[tabId].paneIds.find((id) => model.panes[id]) ?? null;
  return { ...journey, tabId, paneId, detailScroll: 0 };
}

export function openJourneyLevel(journey, model) {
  if (journey.level === "overview") return { ...journey, level: "workspace", detailScroll: 0 };
  if (journey.level === "workspace" && getCurrentPaneId(journey, model)) {
    return { ...journey, paneId: getCurrentPaneId(journey, model), level: "pane", detailScroll: 0 };
  }
  return journey;
}

export function backJourneyLevel(journey) {
  if (journey.level === "pane") return { ...journey, level: "workspace", detailScroll: 0 };
  if (journey.level === "workspace") return { ...journey, level: "overview", detailScroll: 0 };
  return journey;
}

export function scrollDetail(journey, delta) {
  return { ...journey, detailScroll: Math.max(0, (journey.detailScroll ?? 0) + delta) };
}
