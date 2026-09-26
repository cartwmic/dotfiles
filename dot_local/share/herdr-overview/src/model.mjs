export const HERDR_PROTOCOL = 22;

const AGENT_STATES = new Set(["idle", "working", "blocked", "done", "unknown"]);

function objectMap(value) {
  if (value instanceof Map) return Object.fromEntries(value);
  return value && typeof value === "object" ? value : {};
}

function stateOf(value) {
  return AGENT_STATES.has(value) ? value : "unknown";
}

function recapFor(map, kind, id) {
  return objectMap(map)[`${kind}:${id}`] ?? { latest: null, lastAttempt: null };
}

export function normalizeSnapshot(snapshot, supplied = {}, runtime = {}) {
  if (!snapshot || typeof snapshot !== "object") throw new TypeError("session.snapshot must be an object");
  if (snapshot.protocol !== HERDR_PROTOCOL) {
    throw new Error(`Herdr protocol ${HERDR_PROTOCOL} required; server reports ${snapshot.protocol ?? "unknown"}`);
  }

  const promptByPane = objectMap(supplied.promptsByPaneId);
  const promptBySession = objectMap(supplied.promptsBySessionId);
  const recapByPane = objectMap(supplied.piRecapsByPaneId);
  const recapBySession = objectMap(supplied.piRecapsBySessionId);
  const workspaceRecaps = objectMap(supplied.workspaceRecaps);
  const displayNameOwnership = objectMap(runtime.displayNameOwnership);
  const agents = new Map((snapshot.agents ?? []).map((agent) => [agent.pane_id, agent]));
  const workspaces = Object.fromEntries((snapshot.workspaces ?? []).map((workspace) => [workspace.workspace_id, {
    id: workspace.workspace_id,
    number: workspace.number,
    label: workspace.label,
    focused: Boolean(workspace.focused),
    activeTabId: workspace.active_tab_id,
    agentStatus: stateOf(workspace.agent_status),
    tabIds: [],
    recap: recapFor(workspaceRecaps, "workspace", workspace.workspace_id),
    worktree: workspace.worktree ?? null,
    tokens: workspace.tokens ?? {},
  }]));

  const tabs = Object.fromEntries((snapshot.tabs ?? []).map((tab) => [tab.tab_id, {
    id: tab.tab_id,
    workspaceId: tab.workspace_id,
    number: tab.number,
    label: tab.label,
    displayNameOwnership: displayNameOwnership[`tab:${tab.tab_id}`] ?? null,
    focused: Boolean(tab.focused),
    agentStatus: stateOf(tab.agent_status),
    paneIds: [],
  }]));

  for (const tab of Object.values(tabs)) {
    workspaces[tab.workspaceId]?.tabIds.push(tab.id);
  }

  const previousPanes = objectMap(runtime.previousPanes);
  const outputByPane = objectMap(runtime.outputByPaneId);
  const processByPane = objectMap(runtime.processByPaneId);
  const excluded = new Set(runtime.excludedPaneIds ?? []);
  const panes = {};

  for (const nativePane of snapshot.panes ?? []) {
    const id = nativePane.pane_id;
    if (excluded.has(id)) continue;
    const agentInfo = agents.get(id);
    const agentName = agentInfo?.agent ?? nativePane.agent ?? null;
    const agentSession = agentInfo?.agent_session ?? nativePane.agent_session ?? null;
    const piSessionId = agentSession?.agent === "pi" && agentSession.kind === "id" ? agentSession.value : null;
    const previous = previousPanes[id] ?? {};
    const preview = Object.hasOwn(outputByPane, id) ? outputByPane[id] : previous.preview ?? null;
    const processInfo = Object.hasOwn(processByPane, id) ? processByPane[id] : previous.processInfo ?? null;

    panes[id] = {
      id,
      workspaceId: nativePane.workspace_id,
      tabId: nativePane.tab_id,
      label: nativePane.label ?? null,
      displayNameOwnership: displayNameOwnership[`pane:${id}`] ?? null,
      title: nativePane.title ?? null,
      terminalTitle: nativePane.terminal_title_stripped ?? nativePane.terminal_title ?? null,
      cwd: nativePane.cwd ?? null,
      foregroundCwd: nativePane.foreground_cwd ?? agentInfo?.foreground_cwd ?? null,
      focused: Boolean(nativePane.focused),
      agent: {
        present: Boolean(agentInfo || nativePane.agent),
        recognized: Boolean(agentName),
        kind: agentName,
        displayName: agentInfo?.display_agent ?? nativePane.display_agent ?? null,
        name: agentInfo?.name ?? null,
        status: stateOf(agentInfo?.agent_status ?? nativePane.agent_status),
        stateLabels: agentInfo?.state_labels ?? nativePane.state_labels ?? {},
        session: agentSession,
      },
      processInfo,
      preview,
      prompt: promptByPane[id] ?? (piSessionId ? promptBySession[piSessionId] : null) ?? null,
      recap: recapByPane[id] ?? (piSessionId ? recapBySession[piSessionId] : null) ?? { latest: null, lastAttempt: null },
      tokens: nativePane.tokens ?? {},
    };
    tabs[nativePane.tab_id]?.paneIds.push(id);
  }

  for (const workspace of Object.values(workspaces)) {
    workspace.tabIds = workspace.tabIds.filter((id) => tabs[id]);
  }

  return {
    protocol: snapshot.protocol,
    herdrVersion: snapshot.version ?? null,
    selection: {
      workspaceId: snapshot.focused_workspace_id ?? Object.values(workspaces).find((item) => item.focused)?.id ?? null,
      tabId: snapshot.focused_tab_id ?? Object.values(tabs).find((item) => item.focused)?.id ?? null,
      paneId: snapshot.focused_pane_id ?? Object.values(panes).find((item) => item.focused)?.id ?? null,
    },
    workspaceOrder: (snapshot.workspaces ?? []).map((item) => item.workspace_id).filter((id) => workspaces[id]),
    tabOrder: (snapshot.tabs ?? []).map((item) => item.tab_id).filter((id) => tabs[id]),
    paneOrder: (snapshot.panes ?? []).map((item) => item.pane_id).filter((id) => panes[id]),
    workspaces,
    tabs,
    panes,
    recap: supplied.sessionRecap ?? { latest: null, lastAttempt: null },
  };
}
