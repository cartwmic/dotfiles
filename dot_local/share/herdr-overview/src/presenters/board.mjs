const RESET = "\u001b[0m";

function paint(value, token) {
  const color = value?.[token];
  if (!color) return "";
  if (color.kind === "reset") return RESET;
  if (color.kind === "rgb") {
    const parts = color.hex.slice(1).match(/.{2}/g).map((part) => Number.parseInt(part, 16));
    return `\u001b[38;2;${parts.join(";")}m`;
  }
  const codes = { black: 30, red: 31, green: 32, yellow: 33, blue: 34, magenta: 35, purple: 35, cyan: 36, white: 37, gray: 37, grey: 37 };
  return color.kind === "ansi" && codes[color.name] ? `\u001b[${codes[color.name]}m` : "";
}

function safeLines(value) {
  return String(value ?? "")
    .replace(/\u001b\[[0-?]*[ -/]*[@-~]/g, "")
    .replace(/[\u0000-\u0008\u000b-\u001f\u007f]/g, " ")
    .split(/\r?\n/)
    .map((line) => line.replace(/\s+$/g, ""));
}

function compact(value, width) {
  const text = safeLines(value).join(" ").replace(/\s+/g, " ").trim();
  return text.length > width ? `${text.slice(0, Math.max(0, width - 1))}…` : text;
}

function wrapped(value, width) {
  return safeLines(value).flatMap((line) => {
    if (!line) return [""];
    const parts = [];
    for (let index = 0; index < line.length; index += width) parts.push(line.slice(index, index + width));
    return parts;
  });
}

function labelOf(value, fallback) {
  return value?.label || value?.title || value?.terminalTitle || fallback;
}

function processName(pane) {
  const processes = pane.processInfo?.foreground_processes ?? [];
  return processes.map((item) => item.name || item.argv0).filter(Boolean).join(", ") || "unknown";
}

function agentSummary(pane) {
  if (!pane.agent?.present) return "no recognized agent";
  if (!pane.agent.recognized) return `agent unrecognized · ${pane.agent.status || "unknown"}`;
  return `${pane.agent.displayName || pane.agent.kind} · ${pane.agent.status || "unknown"}`;
}

function ageOf(timestamp, now) {
  const value = Date.parse(timestamp ?? "");
  if (!Number.isFinite(value)) return "age unknown";
  const seconds = Math.max(0, Math.floor((now - value) / 1000));
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function recapLines(recap, now, width) {
  const latest = recap?.latest;
  const lastAttempt = recap?.lastAttempt;
  const hasSummary = latest?.status === "published" && typeof latest.summary === "string" && latest.summary.trim();
  const lines = ["Latest recap"];
  if (hasSummary) {
    lines.push(`Published ${ageOf(latest.published_at || latest.created_at, now)}`);
    lines.push(...wrapped(latest.summary, width));
    if (lastAttempt?.status === "failed" && lastAttempt.record_id !== latest.record_id) {
      lines.push("Latest attempt failed");
      if (lastAttempt.failure?.message) lines.push(...wrapped(lastAttempt.failure.message, width));
    }
  } else if (lastAttempt?.status === "failed") {
    lines.push("Unavailable · last attempt failed");
    if (lastAttempt.failure?.message) lines.push(...wrapped(lastAttempt.failure.message, width));
    lines.push(`Attempt ${ageOf(lastAttempt.created_at, now)}`);
  } else if (lastAttempt) {
    lines.push(`Unavailable · last attempt ${compact(lastAttempt.status || "unknown", width - 28)}`);
  } else {
    lines.push("Unavailable · no published recap");
  }
  return lines;
}

function frame(header, body, footer, { width, height, scrollOffset = 0, anchor = null }) {
  const available = Math.max(1, height - header.length - 1);
  const maxStart = Math.max(0, body.length - available);
  let start = Math.min(Math.max(0, scrollOffset), maxStart);
  if (anchor !== null) {
    if (anchor < start) start = anchor;
    else if (anchor >= start + available) start = Math.min(maxStart, anchor - available + 1);
  }
  const visible = body.slice(start, start + available);
  const position = body.length > available ? ` · ${start + 1}-${Math.min(body.length, start + available)}/${body.length}` : "";
  return [...header, ...visible, `${footer}${position}`.slice(0, width)].join("\n");
}

function workspacePaneIds(model, workspace) {
  return workspace.tabIds.flatMap((tabId) => model.tabs[tabId]?.paneIds ?? []).filter((id) => model.panes[id]);
}

export function renderBoardOverview(state, width = 60, height = 24, now = Date.now()) {
  const model = state.model;
  const palette = state.theme?.palette ?? {};
  const sessionRecap = recapLines(model.recap, now, Math.max(24, width - 2));
  sessionRecap[0] = "Herdr session recap";
  const header = [
    `${paint(palette, "accent")}Herdr Overview${RESET} · Board`,
    "All workspaces · summary first",
    ...sessionRecap,
  ];
  const body = [];
  let anchor = null;
  for (const [index, workspaceId] of model.workspaceOrder.entries()) {
    const workspace = model.workspaces[workspaceId];
    if (!workspace) continue;
    const paneIds = workspacePaneIds(model, workspace);
    if (workspaceId === state.journey?.workspaceId) anchor = body.length;
    body.push(`${workspaceId === state.journey?.workspaceId ? "›" : " "} ${paint(palette, "mauve")}${compact(workspace.label || workspace.id, Math.max(8, width - 15))}${RESET}  [${workspace.id}]`);
    body.push(compact(`   ${workspace.tabIds.length} tabs · ${paneIds.length} panes · activity ${workspace.agentStatus || "unknown"}`, width));
    if (workspace.recap?.latest?.status === "published" && workspace.recap.latest.summary) {
      body.push(`   Recap ${ageOf(workspace.recap.latest.published_at || workspace.recap.latest.created_at, now)}`);
    }
    if (index !== model.workspaceOrder.length - 1) body.push("");
  }
  if (!body.length) body.push("No workspaces are available.");
  const footer = width < 54 ? "j/k workspaces · Enter · q close" : "j/k workspace · Enter open · r reread state · q close";
  return frame(header, body, footer, { width, height, anchor });
}

export function renderBoardWorkspace(state, width = 60, height = 24) {
  const model = state.model;
  const palette = state.theme?.palette ?? {};
  const workspace = model.workspaces[state.journey?.workspaceId];
  const header = [
    `${paint(palette, "accent")}Herdr Overview${RESET} · Board · workspace`,
    workspace ? `${workspace.label || workspace.id} [${workspace.id}] · ${workspace.tabIds.length} tabs` : "Workspace unavailable",
  ];
  const body = [];
  let anchor = null;
  for (const tabId of workspace?.tabIds ?? []) {
    const tab = model.tabs[tabId];
    if (!tab) continue;
    body.push(`${paint(palette, "blue")}${compact(`TAB ${tab.number ?? ""} · ${tab.label || tab.id} [${tab.id}]`, Math.max(18, width - 2))}${RESET}`);
    for (const paneId of tab.paneIds) {
      const pane = model.panes[paneId];
      if (!pane) continue;
      if (paneId === state.journey?.paneId) anchor = body.length;
      const selected = paneId === state.journey?.paneId;
      body.push(` ${selected ? "›" : " "} ${compact(`${labelOf(pane, pane.id)} [${pane.id}]`, Math.max(18, width - 6))}`);
      body.push(compact(`     ${agentSummary(pane)} · process ${processName(pane)}`, width));
      if (pane.title || pane.terminalTitle) body.push(compact(`     title ${pane.title || pane.terminalTitle}`, width));
      if (pane.cwd || pane.foregroundCwd) body.push(compact(`     dir ${pane.foregroundCwd || pane.cwd}`, width));
      const preview = safeLines(pane.preview ?? "").filter((line) => line.trim()).slice(-2);
      body.push(compact(`     preview ${preview.length ? preview.join(" · ") : "unavailable"}`, width));
    }
  }
  if (!body.length) body.push("This workspace has no panes.");
  const footer = width < 54 ? "j/k panes · [/] tabs · Enter · f focus · Esc" : "j/k pane · [/] tab · Enter detail · f native focus · Esc back";
  return frame(header, body, footer, { width, height, anchor });
}

export function renderBoardDetail(state, width = 60, height = 24, now = Date.now()) {
  const model = state.model;
  const palette = state.theme?.palette ?? {};
  const pane = model.panes[state.journey?.paneId];
  const header = [
    `${paint(palette, "accent")}Herdr Overview${RESET} · Board · pane detail`,
    pane ? compact(`${labelOf(pane, pane.id)} [${pane.id}] · ${pane.tabId}`, Math.max(20, width - 2)) : "Pane unavailable",
  ];
  const body = [];
  if (!pane) body.push("The selected native pane is no longer available.");
  else {
    body.push("Recent output");
    const recent = safeLines(pane.preview ?? "").filter((line) => line.length > 0);
    body.push(...(recent.length ? recent.flatMap((line) => wrapped(line, Math.max(20, width - 2))) : ["Unavailable · no recent output"]));
    body.push("");
    const prompt = pane.prompt;
    body.push(`Current Pi prompt${prompt?.working === true ? " · working" : prompt?.working === false ? " · settled" : ""}`);
    body.push(...(typeof prompt?.text === "string" && prompt.text.trim()
      ? wrapped(prompt.text, Math.max(20, width - 2))
      : ["Unavailable · no current prompt"]));
    body.push("");
    body.push(...recapLines(pane.recap, now, Math.max(24, width - 2)));
    body.push("");
    body.push("Pane state");
    body.push(compact(`${agentSummary(pane)} · title ${pane.title || pane.terminalTitle || "unavailable"}`, width));
    body.push(compact(`Process ${processName(pane)}`, width));
    body.push(compact(`Directory ${pane.foregroundCwd || pane.cwd || "unavailable"}`, width));
  }
  const footer = width < 54 ? "j/k scroll · Space/b page · f focus · Esc" : "j/k scroll · Space page down · b page up · f focus native pane · Esc back";
  return frame(header, body, footer, {
    width,
    height,
    scrollOffset: state.journey?.detailScroll ?? 0,
  });
}

export function renderBoard(state, width = 60, height = 24, now = Date.now()) {
  if (!state?.model) return "Herdr Overview is waiting for its first session snapshot.";
  if (state.journey?.level === "workspace") return renderBoardWorkspace(state, width, height);
  if (state.journey?.level === "pane") return renderBoardDetail(state, width, height, now);
  return renderBoardOverview(state, width, height, now);
}
