import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import { nativePiSessionId } from "./pi-session-store.mjs";

export function sessionRecapDataRoot(env = process.env) {
  return path.join(env.XDG_DATA_HOME || path.join(os.homedir(), ".local", "share"), "session-recap");
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
  return records.flat().filter(Boolean).map(overviewRecord);
}

// A read-only projection keeps native consumers and legacy records compatible.
// The generic record's narrative, coverage, history identity and source stay untouched.
export function overviewRecord(record) {
  const pi = record?.metadata?.pi;
  if (record?.source_kind !== "pi" || !pi) return record;
  const sessionId = pi.sessionId ?? pi.nativeSessionId;
  if (typeof sessionId !== "string" || !sessionId) return record;
  const herdr = record.annotations?.herdr;
  return { ...record, source_kind: "pi-session", source_id: sessionId,
    pane_id: herdr?.pane_id, workspace_id: herdr?.workspace_id,
    overview_attributed: Object.hasOwn(record.annotations ?? {}, "herdr") };
}

export async function readLatestRecapRecords(root = sessionRecapDataRoot(), sourceKind = null) {
  const latest = new Map();
  for (const record of await readAllRecapRecords(root)) {
    if (record.status !== "published" || record.overview_attributed === false
      || (sourceKind && record.source_kind !== sourceKind)) continue;
    const key = JSON.stringify([record.source_kind, record.source_id]);
    latest.set(key, newerRecord(latest.get(key), record, "published_at"));
  }
  return [...latest.values()];
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
  const bySession = new Map();
  // Read old prompt files without migrating or deleting them; adapter-owned files win.
  for (const directory of [path.join(root, "prompts"), path.join(path.dirname(root), "herdr-overview", "prompts")]) {
    try {
      for (const name of await readdir(directory)) {
        if (!name.endsWith(".json")) continue;
        const prompt = await readJson(path.join(directory, name));
        if (prompt?.schema_version === 1 && typeof prompt.session_id === "string") bySession.set(prompt.session_id, prompt);
      }
    } catch { /* Missing prompt directories are normal. */ }
  }
  return [...bySession.values()];
}

export async function readRecapFields(
  snapshot,
  root = sessionRecapDataRoot(),
  piTerminalIdsBySessionId = {},
  manualTerminalIdsBySourceId = {},
  rekeyedPanes = [],
) {
  const all = await readAllRecapRecords(root);
  const legacyIndex = await readJson(path.join(root, "latest.json"));
  const sources = [...new Map(all.map(record => [JSON.stringify([record.source_kind, record.source_id]),
    { source_kind: record.source_kind, source_id: record.source_id }])).values()];

  async function bySource(sourceKind, sourceId) {
    const records = all.filter(record => record.source_kind === sourceKind && record.source_id === sourceId);
    const latest = records.filter(record => record.status === "published").reduce((a, b) => newerRecord(a, b, "published_at"), null);
    const lastAttempt = records.reduce((a, b) => newerRecord(a, b, "created_at"), null);
    // Legacy writers used latest.json to distinguish same-timestamp attempts.
    // Only a validated legacy record tied with history's newest can break a tie;
    // missing/stale indices and generic Pi records remain history-authoritative.
    const index = Array.isArray(legacyIndex?.sources) ? legacyIndex.sources.find(item =>
      item?.source_kind === sourceKind && item?.source_id === sourceId) : null;
    const tie = (newest, id, field, publishedOnly = false) => {
      if (!newest || sourceKind !== "pi-session") return newest;
      const pointed = records.find(record => record.record_id === id
        && record.overview_attributed === undefined
        && (publishedOnly ? record.status === "published" : ["published", "failed"].includes(record.status)));
      const validTime = record => Number.isFinite(Date.parse(record?.[field] ?? record?.published_at ?? record?.created_at ?? ""));
      return pointed && validTime(pointed) && validTime(newest)
        && recordTime(pointed, field) === recordTime(newest, field) ? pointed : newest;
    };
    return {
      latest: tie(latest, index?.latest_success_id, "published_at", true),
      lastAttempt: tie(lastAttempt, index?.last_attempt_id, "created_at"),
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
    const sessionId = nativePiSessionId(session);
    if (!sessionId) continue;
    const recap = piRecapsBySessionId[sessionId];
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
