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

function plain(value) {
  return String(value ?? "")
    .replace(/\u001b\[[0-?]*[ -/]*[@-~]/g, "")
    .replace(/[\u0000-\u001f\u007f]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function compact(value, width) {
  const text = plain(value);
  return text.length > width ? `${text.slice(0, Math.max(0, width - 1))}…` : text;
}

function wrapped(value, width) {
  const text = plain(value);
  if (!text) return [""];
  const lines = [];
  for (let index = 0; index < text.length; index += width) lines.push(text.slice(index, index + width));
  return lines;
}

function labelOf(value, fallback) {
  return value?.label || value?.title || value?.terminalTitle || fallback;
}

function paneStatus(pane) {
  if (!pane.agent?.present) return "no agent";
  if (!pane.agent.recognized) return `unrecognized · ${pane.agent.status || "unknown"}`;
  return `${pane.agent.displayName || pane.agent.kind} · ${pane.agent.status || "unknown"}`;
}

function processName(pane) {
  return (pane.processInfo?.foreground_processes ?? []).map((item) => item.name || item.argv0).filter(Boolean).join(", ") || "unknown process";
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
  const attempt = recap?.lastAttempt;
  const hasSummary = latest?.status === "published" && typeof latest.summary === "string" && latest.summary.trim();
  const result = ["LATEST PUBLISHED RECAP"];
  if (hasSummary) {
    result.push(`Published ${ageOf(latest.published_at || latest.created_at, now)}`);
    result.push(...wrapped(latest.summary, width));
    if (attempt?.status === "failed" && attempt.record_id !== latest.record_id) {
      result.push("Latest attempt failed");
      if (attempt.failure?.message) result.push(...wrapped(attempt.failure.message, width));
    }
  } else if (attempt?.status === "failed") {
    result.push("Unavailable · last attempt failed");
    if (attempt.failure?.message) result.push(...wrapped(attempt.failure.message, width));
    result.push(`Attempt ${ageOf(attempt.created_at, now)}`);
  } else if (attempt) {
    result.push(`Unavailable · last attempt ${plain(attempt.status || "unknown")}`);
  } else {
    result.push("Unavailable · no published recap");
  }
  return result;
}

function section(title, width, first = false) {
  const prefix = first ? `┏━ ${title} ` : `┣━ ${title} `;
  return `${prefix}${"━".repeat(Math.max(0, width - prefix.length))}`;
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
  const position = body.length > available ? ` · rows ${start + 1}-${Math.min(body.length, start + available)}/${body.length}` : "";
  return [...header, ...visible, `${footer}${position}`.slice(0, width)].join("\n");
}

function grid(panes, columns, cardWidth, makeCard) {
  const body = [];
  const anchors = new Map();
  for (let offset = 0; offset < panes.length; offset += columns) {
    const row = panes.slice(offset, offset + columns);
    const cards = row.map((pane) => makeCard(pane, cardWidth));
    const height = Math.max(...cards.map((card) => card.length));
    for (const pane of row) anchors.set(pane.id, body.length);
    for (let line = 0; line < height; line += 1) {
      const bodyLine = cards.map((card) => (card[line] ?? "").padEnd(cardWidth)).join("  ").replace(/\s+$/, "");
      body.push(bodyLine);
    }
    body.push("");
  }
  return { body, anchors };
}

function paneCard(pane, tabLabel, width, selected) {
  const inner = Math.max(16, width - 4);
  const border = `+${"-".repeat(width - 2)}+`;
  const title = `${selected ? ">" : " "} ${tabLabel} / ${labelOf(pane, pane.id)} [${pane.id}]`;
  const preview = plain((pane.preview ?? "").split(/\r?\n/).filter(Boolean).at(-1)) || "preview unavailable";
  const status = `${paneStatus(pane)} · ${processName(pane)}`;
  return [
    border,
    `| ${plain(title).slice(0, inner).padEnd(inner)} |`,
    `| ${plain(status).slice(0, inner).padEnd(inner)} |`,
    `| ${preview.slice(0, inner).padEnd(inner)} |`,
    border,
  ];
}

function paneEntries(model, workspace) {
  return workspace.tabIds.flatMap((tabId) => {
    const tab = model.tabs[tabId];
    return (tab?.paneIds ?? []).map((paneId) => ({ pane: model.panes[paneId], tabLabel: tab?.label || tab?.id })).filter((item) => item.pane);
  });
}

export function renderMosaicOverview(state, width = 100, height = 24, now = Date.now()) {
  const model = state.model;
  const palette = state.theme?.palette ?? {};
  const sessionRecap = recapLines(model.recap, now, Math.max(24, width - 2));
  sessionRecap[0] = "Herdr session recap";
  const header = [
    `${paint(palette, "accent")}Herdr Overview${RESET} · Mosaic`,
    "All workspaces · every pane · simultaneous previews",
    ...sessionRecap,
  ];
  const body = [];
  let anchor = null;
  const columns = Math.max(1, Math.floor((width - 4) / 36));
  const cardWidth = Math.max(28, Math.min(48, Math.floor((width - 4) / columns)));
  for (const workspaceId of model.workspaceOrder) {
    const workspace = model.workspaces[workspaceId];
    if (!workspace) continue;
    if (workspaceId === state.journey?.workspaceId) anchor = body.length;
    const entries = paneEntries(model, workspace);
    const marker = workspaceId === state.journey?.workspaceId ? "›" : " ";
    const workspaceLabel = compact(workspace.label || workspace.id, Math.max(8, width - workspace.id.length - 25));
    body.push(`${marker} ${paint(palette, "mauve")}${workspaceLabel}${RESET} [${workspace.id}] · ${workspace.tabIds.length} tabs · ${entries.length} panes`);
    if (!entries.length) body.push("  (no panes)");
    else {
      const result = grid(entries.map((item) => ({ ...item.pane, tabLabel: item.tabLabel })), columns, cardWidth, (pane, card) => paneCard(pane, pane.tabLabel, card, pane.id === state.journey?.paneId));
      if (anchor === body.length) anchor = body.length;
      body.push(...result.body);
    }
  }
  if (!body.length) body.push("No workspaces are available.");
  const footer = width < 80 ? "j/k workspaces · Enter · q close" : "j/k workspace · Enter open · r reread state · q close";
  return frame(header, body, footer, { width, height, anchor });
}

export function renderMosaicWorkspace(state, width = 100, height = 24) {
  const model = state.model;
  const palette = state.theme?.palette ?? {};
  const workspace = model.workspaces[state.journey?.workspaceId];
  const header = [
    `${paint(palette, "accent")}Herdr Overview${RESET} · Mosaic · workspace`,
    workspace ? compact(`${workspace.label || workspace.id} [${workspace.id}] · tab-grouped preview grid`, Math.max(20, width - 2)) : "Workspace unavailable",
  ];
  const body = [];
  let anchor = null;
  const columns = Math.max(1, Math.floor((width - 4) / 36));
  const cardWidth = Math.max(28, Math.min(48, Math.floor((width - 4) / columns)));
  for (const tabId of workspace?.tabIds ?? []) {
    const tab = model.tabs[tabId];
    if (!tab) continue;
    body.push(`${paint(palette, "blue")}${compact(`TAB ${tab.number ?? ""} · ${tab.label || tab.id} [${tab.id}]`, Math.max(20, width - 2))}${RESET}`);
    const entries = tab.paneIds.map((paneId) => model.panes[paneId]).filter(Boolean);
    if (!entries.length) body.push("  (no panes)");
    else {
      const result = grid(entries, columns, cardWidth, (pane, card) => paneCard(pane, tab.label || tab.id, card, pane.id === state.journey?.paneId));
      if (result.anchors.has(state.journey?.paneId)) anchor = body.length + result.anchors.get(state.journey.paneId);
      else if (anchor === null && entries.some((pane) => pane.id === state.journey?.paneId)) anchor = body.length;
      body.push(...result.body);
    }
  }
  if (!body.length) body.push("This workspace has no tabs.");
  const footer = width < 80 ? "j/k panes · [/] tabs · Enter · f focus · Esc" : "j/k pane · [/] tab · Enter detail · f native focus · Esc back";
  return frame(header, body, footer, { width, height, anchor });
}

export function renderMosaicDetail(state, width = 100, height = 24, now = Date.now()) {
  const model = state.model;
  const palette = state.theme?.palette ?? {};
  const pane = model.panes[state.journey?.paneId];
  const header = [
    `${paint(palette, "accent")}Herdr Overview${RESET} · Mosaic · selected pane`,
    pane ? compact(`${labelOf(pane, pane.id)} [${pane.id}] · ${pane.tabId}`, Math.max(20, width - 2)) : "Pane unavailable",
  ];
  const body = [];
  if (!pane) body.push("Selected native pane is unavailable.");
  else {
    body.push(section("RECENT OUTPUT", width, true));
    const recent = (pane.preview ?? "").split(/\r?\n/).filter((line) => line.trim());
    body.push(...(recent.length ? recent.flatMap((line) => wrapped(line, Math.max(24, width - 4))) : ["Unavailable · no recent output"]));
    body.push(section("CURRENT PI PROMPT", width));
    const prompt = pane.prompt;
    body.push(...(typeof prompt?.text === "string" && prompt.text.trim()
      ? [prompt.working === true ? "Working" : prompt.working === false ? "Settled" : "Available", ...prompt.text.split(/\r?\n/).flatMap((line) => wrapped(line, Math.max(24, width - 4)))]
      : ["Unavailable · no current prompt"]));
    body.push(section("LATEST PUBLISHED RECAP", width));
    body.push(...recapLines(pane.recap, now, Math.max(24, width - 4)));
    body.push(section("NATIVE PANE", width));
    body.push(...wrapped(`Agent: ${paneStatus(pane)}`, Math.max(24, width - 2)));
    body.push(...wrapped(`Title: ${pane.title || pane.terminalTitle || "unavailable"}`, Math.max(24, width - 2)));
    body.push(...wrapped(`Process: ${processName(pane)}`, Math.max(24, width - 2)));
    body.push(...wrapped(`Directory: ${pane.foregroundCwd || pane.cwd || "unavailable"}`, Math.max(24, width - 2)));
    body.push(...wrapped(`Tab: ${pane.tabId} · Workspace: ${pane.workspaceId}`, Math.max(24, width - 2)));
    body.push(`┗${"━".repeat(Math.max(0, width - 1))}`);
  }
  const footer = width < 80 ? "j/k scroll · Space/b page · f focus · Esc" : "j/k scroll · Space page down · b page up · f focus native pane · Esc back";
  return frame(header, body, footer, {
    width,
    height,
    scrollOffset: state.journey?.detailScroll ?? 0,
  });
}

export function renderMosaic(state, width = 100, height = 24, now = Date.now()) {
  if (!state?.model) return "Herdr Overview is waiting for its first session snapshot.";
  if (state.journey?.level === "workspace") return renderMosaicWorkspace(state, width, height);
  if (state.journey?.level === "pane") return renderMosaicDetail(state, width, height, now);
  return renderMosaicOverview(state, width, height, now);
}
