import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import os from "node:os";

export function sessionRecapDataRoot(env = process.env) {
  return path.join(env.XDG_DATA_HOME || path.join(os.homedir(), ".local", "share"), "session-recap");
}

function encodeSessionId(sessionId) {
  return encodeURIComponent(sessionId).replace(/[!'()*]/g, (char) => `%${char.charCodeAt(0).toString(16).toUpperCase()}`);
}

async function readJson(filePath) {
  try {
    const value = JSON.parse(await readFile(filePath, "utf8"));
    return value && typeof value === "object" ? value : null;
  } catch {
    return null;
  }
}

async function recordDays(root) {
  try {
    return (await readdir(path.join(root, "records"), { withFileTypes: true }))
      .filter((entry) => entry.isDirectory() && /^\d{4}-\d{2}-\d{2}$/.test(entry.name))
      .map((entry) => entry.name)
      .sort()
      .reverse();
  } catch {
    return [];
  }
}

async function recordPath(root, recordId, dayNames) {
  if (typeof recordId !== "string" || !recordId) return null;
  for (const day of dayNames) {
    const candidate = path.join(root, "records", day, `${recordId}.json`);
    try {
      await readFile(candidate, "utf8");
      return candidate;
    } catch {
      // Continue through dated record directories; the latest index stores IDs, not dates.
    }
  }
  return null;
}

async function readRecord(root, recordId, dayNames) {
  const filePath = await recordPath(root, recordId, dayNames);
  return filePath ? readJson(filePath) : null;
}

export async function readAllRecapRecords(root = sessionRecapDataRoot()) {
  const days = await recordDays(root);
  const records = await Promise.all(days.map(async (day) => {
    const directory = path.join(root, "records", day);
    let names;
    try {
      names = await readdir(directory);
    } catch {
      return [];
    }
    return Promise.all(names.filter((name) => name.endsWith(".json")).map((name) => readJson(path.join(directory, name))));
  }));
  return records.flat().filter(Boolean);
}

export async function readLatestRecapRecords(root = sessionRecapDataRoot(), sourceKind = null) {
  const latestIndex = await readJson(path.join(root, "latest.json"));
  const sources = Array.isArray(latestIndex?.sources) ? latestIndex.sources : [];
  const days = await recordDays(root);
  const records = await Promise.all(sources
    .filter((item) => item && typeof item === "object"
      && (!sourceKind || item.source_kind === sourceKind)
      && typeof item.latest_success_id === "string")
    .map((item) => readRecord(root, item.latest_success_id, days)));
  return records.filter((record) => record?.status === "published");
}

function recordTime(record, field) {
  const value = Date.parse(record?.[field] ?? record?.published_at ?? record?.created_at ?? "");
  return Number.isFinite(value) ? value : 0;
}

function newerRecord(left, right, field) {
  if (!left) return right ?? null;
  if (!right) return left;
  const timeDifference = recordTime(right, field) - recordTime(left, field);
  if (timeDifference !== 0) return timeDifference > 0 ? right : left;
  return String(right.record_id ?? "").localeCompare(String(left.record_id ?? "")) >= 0 ? right : left;
}

function mergeRecapFields(current, incoming) {
  return {
    latest: newerRecord(current?.latest, incoming?.latest, "published_at"),
    lastAttempt: newerRecord(current?.lastAttempt, incoming?.lastAttempt, "created_at"),
  };
}

export async function readCurrentPiPrompts(root = sessionRecapDataRoot()) {
  try {
    const files = await readdir(path.join(root, "prompts"), { withFileTypes: true });
    const prompts = await Promise.all(files
      .filter((entry) => entry.isFile() && entry.name.endsWith(".json"))
      .map((entry) => readJson(path.join(root, "prompts", entry.name))));
    return prompts.filter((prompt) => prompt?.schema_version === 1 && typeof prompt.session_id === "string");
  } catch {
    return [];
  }
}

export async function readRecapFields(
  snapshot,
  root = sessionRecapDataRoot(),
  piTerminalIdsBySessionId = {},
  manualTerminalIdsBySourceId = {},
  rekeyedPanes = [],
) {
  const latestIndex = await readJson(path.join(root, "latest.json"));
  const sources = Array.isArray(latestIndex?.sources) ? latestIndex.sources : [];
  const dayNames = await recordDays(root);

  async function bySource(sourceKind, sourceId) {
    const entry = sources.find((item) => item?.source_kind === sourceKind && item?.source_id === sourceId);
    if (!entry) return { latest: null, lastAttempt: null };
    const [latest, lastAttempt] = await Promise.all([
      readRecord(root, entry.latest_success_id, dayNames),
      readRecord(root, entry.last_attempt_id, dayNames),
    ]);
    return {
      latest: latest?.status === "published" ? latest : null,
      lastAttempt: lastAttempt ?? null,
    };
  }

  const promptsBySessionId = {};
  const promptsByPaneId = {};
  const piTerminalIds = { ...piTerminalIdsBySessionId };
  for (const prompt of await readCurrentPiPrompts(root)) {
    promptsBySessionId[prompt.session_id] = prompt;
    if (typeof prompt.pane_id === "string") promptsByPaneId[prompt.pane_id] = prompt;
    const rekey = rekeyedPanes.find((pane) => pane.previousPaneId === prompt.pane_id);
    if (rekey) piTerminalIds[prompt.session_id] = rekey.terminalId;
  }

  const panesByTerminalId = new Map((snapshot.panes ?? [])
    .filter((pane) => typeof pane.terminal_id === "string" && pane.terminal_id
      && snapshot.panes.filter((other) => other.terminal_id === pane.terminal_id).length === 1)
    .map((pane) => [pane.terminal_id, pane]));
  // A Pi prompt can still carry the pane ID inherited before pane.move. Follow
  // the persisted session-to-terminal association to the current native ID;
  // Herdr 0.9.1 may not expose agent_session on the moved pane.
  for (const [sessionId, terminalId] of Object.entries(piTerminalIds)) {
    const pane = panesByTerminalId.get(terminalId);
    const prompt = promptsBySessionId[sessionId];
    if (pane && prompt) promptsByPaneId[pane.pane_id] = prompt;
  }

  const piRecapsBySessionId = {};
  const piRecapsByPaneId = {};
  const recapsByPaneId = {};
  const paneIds = new Set((snapshot.panes ?? []).map((pane) => pane.pane_id).filter((id) => typeof id === "string"));
  const recapReads = await Promise.all(sources
    .filter((item) => item && typeof item === "object"
      && typeof item.source_kind === "string" && typeof item.source_id === "string")
    .map(async (item) => ({
      sourceKind: item.source_kind,
      sourceId: item.source_id,
      recap: await bySource(item.source_kind, item.source_id),
    })));
  for (const { sourceKind, sourceId, recap } of recapReads) {
    if (sourceKind === "pi-session") piRecapsBySessionId[sourceId] = recap;
    const attributedPaneId = recap.lastAttempt?.pane_id ?? recap.latest?.pane_id;
    const manualTerminalId = sourceKind === "manual" ? manualTerminalIdsBySourceId?.[sourceId] : null;
    let paneId;
    if (sourceKind === "manual") {
      if (manualTerminalId) paneId = panesByTerminalId.get(manualTerminalId)?.pane_id ?? null;
      else if (paneIds.has(sourceId)) paneId = sourceId;
    } else if (paneIds.has(attributedPaneId)) {
      paneId = attributedPaneId;
    }
    if (!paneId || (!recap.latest && !recap.lastAttempt)) continue;
    recapsByPaneId[paneId] = mergeRecapFields(recapsByPaneId[paneId], recap);
    if (sourceKind === "pi-session") {
      piRecapsByPaneId[paneId] = mergeRecapFields(piRecapsByPaneId[paneId], recap);
    }
  }

  // Herdr can rekey a pane ID on pane.move. Use the durable terminal-ID
  // association learned while the published recap still named the live pane;
  // keep the old publication pane/workspace fields untouched for naming.
  for (const [sessionId, terminalId] of Object.entries(piTerminalIds)) {
    const pane = panesByTerminalId.get(terminalId);
    const recap = piRecapsBySessionId[sessionId];
    if (pane && recap) recapsByPaneId[pane.pane_id] = mergeRecapFields(recapsByPaneId[pane.pane_id], recap);
  }

  // Preserve native agent-session matching when v0.9.1 supplies it, but do not
  // require it: real Pi panes can report agent=pi with agent_session=null.
  const agentByPaneId = new Map((snapshot.agents ?? []).map((agent) => [agent.pane_id, agent]));
  for (const pane of snapshot.panes ?? []) {
    const agent = agentByPaneId.get(pane.pane_id);
    const session = agent?.agent_session ?? pane.agent_session;
    if (session?.agent !== "pi" || session.kind !== "id" || typeof session.value !== "string") continue;
    const recap = piRecapsBySessionId[session.value];
    if (recap) recapsByPaneId[pane.pane_id] = mergeRecapFields(recapsByPaneId[pane.pane_id], recap);
  }

  const workspaceRecaps = {};
  for (const workspace of snapshot.workspaces ?? []) {
    workspaceRecaps[`workspace:${workspace.workspace_id}`] = await bySource("workspace", workspace.workspace_id);
  }

  return {
    promptsByPaneId,
    promptsBySessionId,
    piTerminalIdsBySessionId: piTerminalIds,
    recapsByPaneId,
    piRecapsByPaneId,
    piRecapsBySessionId,
    workspaceRecaps,
    sessionRecap: await bySource("herdr-session", "active"),
  };
}
