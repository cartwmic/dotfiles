import path from "node:path";

const DEFAULT_PROCESS_NAMES = new Set(["bash", "zsh", "sh", "dash", "fish", "nu", "pwsh", "powershell"]);

function objectMap(value) {
  if (value instanceof Map) return Object.fromEntries(value);
  return value && typeof value === "object" ? value : {};
}

function normalizedLabel(value) {
  if (typeof value !== "string") return null;
  const label = value.replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim();
  return label || null;
}

function shortLabel(value, limit = 72) {
  const label = normalizedLabel(value);
  if (!label) return null;
  return label.length > limit ? `${label.slice(0, limit - 1).trimEnd()}…` : label;
}

function keyFor(kind, id) {
  return `${kind}:${id}`;
}

function paneRecapLabel(pane, agentSession, supplied) {
  const byPane = objectMap(supplied.piRecapsByPaneId)[pane.pane_id];
  const bySession = agentSession?.kind === "id"
    ? objectMap(supplied.piRecapsBySessionId)[agentSession.value]
    : null;

  for (const recap of [byPane, bySession]) {
    const latest = recap?.latest;
    if (latest?.status !== "published"
      || latest.source_kind !== "pi-session"
      || latest.pane_id !== pane.pane_id
      || latest.workspace_id !== pane.workspace_id) continue;
    const label = shortLabel(latest.summary, 72);
    if (label) return label;
  }
  return null;
}

function processLabel(processInfo) {
  const processes = processInfo?.foreground_processes ?? [];
  for (const process of processes) {
    const name = path.basename(String(process.name ?? process.argv0 ?? "").split(/\s+/)[0]).trim();
    if (name && !DEFAULT_PROCESS_NAMES.has(name.toLowerCase())) return name;
  }
  return processes.length ? path.basename(String(processes[0].name ?? processes[0].argv0 ?? "")).trim() || null : null;
}

function paneTaskLabel(pane, agentInfo, processInfo, supplied) {
  const agentName = agentInfo?.agent ?? pane.agent ?? null;
  const agentSession = agentInfo?.agent_session ?? pane.agent_session ?? null;
  if (agentName === "pi" || agentSession?.agent === "pi") {
    return paneRecapLabel(pane, agentSession, supplied);
  }

  const title = shortLabel(pane.title) ?? shortLabel(pane.terminal_title_stripped) ?? shortLabel(pane.terminal_title);
  if (title) return title;

  const cwd = [pane.foreground_cwd, agentInfo?.foreground_cwd, pane.cwd]
    .find((value) => typeof value === "string" && value.trim());
  const directory = cwd ? path.basename(String(cwd).replace(/[\\/]+$/, "")) : "";
  const subject = shortLabel(agentInfo?.display_agent, 48)
    ?? shortLabel(pane.display_agent, 48)
    ?? shortLabel(processLabel(processInfo), 48);
  if (subject && directory) return shortLabel(`${subject} · ${directory}`, 72);
  return subject ?? shortLabel(directory);
}

function isKnownDefault(kind, label, defaultLabel) {
  return label === null || (kind === "tab" && label === defaultLabel);
}

function validEntry(entry) {
  return entry && (entry.mode === "automatic" || entry.mode === "manual");
}

function ownershipFor(kind, item, previous, resetName, defaultLabel = null) {
  const currentLabel = normalizedLabel(item.label);
  const isReset = resetName?.kind === kind && resetName.id === item[`${kind}_id`];
  if (isReset) {
    return {
      mode: "automatic",
      lastWrittenLabel: previous?.lastWrittenLabel ?? null,
      observedLabel: currentLabel,
      defaultLabel: isKnownDefault(kind, currentLabel, defaultLabel) ? defaultLabel : null,
    };
  }

  if (!validEntry(previous)) {
    return {
      mode: isKnownDefault(kind, currentLabel, defaultLabel) ? "automatic" : "manual",
      lastWrittenLabel: null,
      observedLabel: currentLabel,
      defaultLabel: isKnownDefault(kind, currentLabel, defaultLabel) ? defaultLabel : null,
    };
  }

  if (previous.mode === "manual") {
    return { ...previous, mode: "manual", observedLabel: currentLabel, defaultLabel: null };
  }

  const labelChanged = normalizedLabel(previous.observedLabel) !== currentLabel;
  const defaultRepositioned = kind === "tab"
    && previous.lastWrittenLabel == null
    && previous.defaultLabel != null
    && normalizedLabel(previous.observedLabel) === previous.defaultLabel
    && currentLabel === defaultLabel;
  if (labelChanged && !defaultRepositioned) {
    return {
      ...previous,
      mode: "manual",
      observedLabel: currentLabel,
      defaultLabel: null,
    };
  }

  return {
    ...previous,
    mode: "automatic",
    observedLabel: currentLabel,
    defaultLabel: isKnownDefault(kind, currentLabel, defaultLabel) ? defaultLabel : null,
  };
}

function nativeId(kind, item) {
  return kind === "pane" ? item.pane_id : item.tab_id;
}

export function evaluateDisplayNamePolicy(snapshot, {
  processByPaneId = {},
  supplied = {},
  ownership = {},
  resetName = null,
  excludedPaneIds = [],
} = {}) {
  if (resetName && (!new Set(["pane", "tab"]).has(resetName.kind) || typeof resetName.id !== "string")) {
    throw new TypeError("automatic name reset requires a pane or tab ID");
  }

  const previous = objectMap(ownership);
  const processes = objectMap(processByPaneId);
  const excluded = new Set(excludedPaneIds);
  const nextSnapshot = {
    ...snapshot,
    panes: (snapshot.panes ?? []).map((pane) => ({ ...pane })),
    tabs: (snapshot.tabs ?? []).map((tab) => ({ ...tab })),
  };
  const nextOwnership = {};
  const rename = [];
  const paneLabels = new Map();
  const tabDefaults = new Map();
  const tabPositions = new Map();
  for (const tab of nextSnapshot.tabs) {
    const position = (tabPositions.get(tab.workspace_id) ?? 0) + 1;
    tabPositions.set(tab.workspace_id, position);
    tabDefaults.set(tab.tab_id, String(position));
  }
  const agentByPane = new Map((snapshot.agents ?? []).map((agent) => [agent.pane_id, agent]));

  for (const pane of nextSnapshot.panes) {
    const id = nativeId("pane", pane);
    if (excluded.has(id)) continue;
    const agentInfo = agentByPane.get(id);
    const entry = ownershipFor("pane", pane, previous[keyFor("pane", id)], resetName);
    nextOwnership[keyFor("pane", id)] = entry;
    const candidate = paneTaskLabel(pane, agentInfo, processes[id], supplied);
    paneLabels.set(id, candidate);
    if (entry.mode === "automatic" && candidate && candidate !== normalizedLabel(pane.label)) {
      rename.push({ kind: "pane", id, label: candidate });
    }
  }

  const paneIdsByTab = new Map();
  for (const pane of nextSnapshot.panes) {
    if (excluded.has(pane.pane_id)) continue;
    const paneIds = paneIdsByTab.get(pane.tab_id) ?? [];
    paneIds.push(pane.pane_id);
    paneIdsByTab.set(pane.tab_id, paneIds);
  }

  for (const tab of nextSnapshot.tabs) {
    const id = nativeId("tab", tab);
    const paneIds = paneIdsByTab.get(id) ?? [];
    if (!paneIds.length) continue;
    const entry = ownershipFor("tab", tab, previous[keyFor("tab", id)], resetName, tabDefaults.get(id));
    nextOwnership[keyFor("tab", id)] = entry;
    const taskLabels = paneIds.map((paneId) => paneLabels.get(paneId)).filter(Boolean);
    const candidate = taskLabels.length ? shortLabel(taskLabels.join(" + "), 160) : null;
    if (entry.mode === "automatic" && candidate && candidate !== normalizedLabel(tab.label)) {
      rename.push({ kind: "tab", id, label: candidate });
    }
  }

  if (resetName && !nextOwnership[keyFor(resetName.kind, resetName.id)]) {
    throw new Error(`cannot return unknown or excluded ${resetName.kind} ${resetName.id} to automatic naming`);
  }

  return { snapshot: nextSnapshot, ownership: nextOwnership, rename };
}

export function recordDisplayNameWrite(policy, { kind, id, label }) {
  const collection = kind === "pane" ? policy.snapshot.panes : policy.snapshot.tabs;
  const field = kind === "pane" ? "pane_id" : "tab_id";
  const item = collection.find((candidate) => candidate[field] === id);
  const entry = policy.ownership[keyFor(kind, id)];
  if (!item || !entry || entry.mode !== "automatic") throw new Error(`cannot record automatic ${kind} name for ${id}`);
  item.label = label;
  entry.lastWrittenLabel = label;
  entry.observedLabel = normalizedLabel(label);
  entry.defaultLabel = null;
}

export function displayNameResetFromContext(context, kind) {
  const root = context && typeof context === "object" ? context : {};
  const candidates = [root.context, root.selection, root].filter((value) => value && typeof value === "object");
  const target = candidates.find((value) => kind === "pane"
    ? value.focused_pane_id || value.pane_id
    : kind === "tab" ? value.tab_id : false) ?? {};
  const id = kind === "pane" ? target.focused_pane_id ?? target.pane_id : target.tab_id;
  if (!new Set(["pane", "tab"]).has(kind) || typeof id !== "string" || !id) {
    throw new Error("automatic naming action needs the selected pane or tab ID");
  }
  return { kind, id };
}
