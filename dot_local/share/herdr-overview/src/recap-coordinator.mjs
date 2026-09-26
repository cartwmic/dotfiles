import { spawn } from "node:child_process";
import os from "node:os";
import path from "node:path";
import { readAllRecapRecords, readLatestRecapRecords } from "./recap-store.mjs";

export const WORKSPACE_QUIET_PERIOD_MS = 30_000;
const MAX_COMMAND_OUTPUT = 64 * 1024;
const COMMAND_TIMEOUT_MS = 5 * 60 * 1_000;

function recapCommandPath(env = process.env) {
  return env.SESSION_RECAP_BIN?.trim() || path.join(env.HOME || os.homedir(), ".local", "bin", "session-recap");
}

export function runSessionRecap(args, input = "", { bin = recapCommandPath(), env = process.env } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(bin, args, { stdio: ["pipe", "pipe", "pipe"], env });
    let stdout = "";
    let stderr = "";
    let settled = false;
    let outputTooLarge = false;
    const finish = (error, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      if (error) reject(error);
      else resolve(value);
    };
    const timeout = setTimeout(() => {
      child.kill("SIGTERM");
      finish(new Error("session-recap timed out"));
    }, COMMAND_TIMEOUT_MS);
    timeout.unref?.();

    child.once("error", (error) => finish(new Error(`could not start session-recap: ${error.message}`)));
    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString("utf8");
      if (Buffer.byteLength(stdout, "utf8") > MAX_COMMAND_OUTPUT) {
        outputTooLarge = true;
        child.kill("SIGTERM");
      }
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString("utf8");
      if (Buffer.byteLength(stderr, "utf8") > MAX_COMMAND_OUTPUT) stderr = stderr.slice(-MAX_COMMAND_OUTPUT);
    });
    child.stdin.on("error", () => {});
    child.once("close", (code, signal) => {
      if (outputTooLarge) finish(new Error("session-recap returned too much output"));
      else if (code !== 0) {
        const detail = stderr.trim();
        finish(new Error(detail || `session-recap exited with ${signal ?? code}`));
      } else finish(undefined, stdout.trim());
    });
    child.stdin.end(input, "utf8");
  });
}

function normalizedState(value = {}) {
  value ??= {};
  const processedRecordIds = Array.isArray(value.processedRecordIds)
    ? [...new Set(value.processedRecordIds.filter((id) => typeof id === "string" && id))]
    : [];
  const workspaceDeadlines = {};
  if (value.workspaceDeadlines && typeof value.workspaceDeadlines === "object") {
    for (const [workspaceId, deadline] of Object.entries(value.workspaceDeadlines)) {
      if (typeof workspaceId === "string" && workspaceId && typeof deadline === "string" && Number.isFinite(Date.parse(deadline))) {
        workspaceDeadlines[workspaceId] = new Date(Date.parse(deadline)).toISOString();
      }
    }
  }
  const piTerminalIdsBySessionId = {};
  if (value.piTerminalIdsBySessionId && typeof value.piTerminalIdsBySessionId === "object") {
    for (const [sessionId, terminalId] of Object.entries(value.piTerminalIdsBySessionId)) {
      if (sessionId && typeof terminalId === "string" && terminalId) piTerminalIdsBySessionId[sessionId] = terminalId;
    }
  }
  return { schema_version: 1, processedRecordIds, workspaceDeadlines, piTerminalIdsBySessionId };
}

function publicationTime(record, fallback) {
  const value = Date.parse(record.published_at ?? record.created_at ?? "");
  return Number.isFinite(value) ? value : fallback;
}

function compareRecords(left, right) {
  const leftTime = publicationTime(left, 0);
  const rightTime = publicationTime(right, 0);
  return leftTime - rightTime || String(left.record_id).localeCompare(String(right.record_id));
}

function groupMember(record) {
  const member = { record_id: record.record_id, text: record.summary };
  if (typeof record.label === "string" && record.label.trim()) member.label = record.label;
  return member;
}

async function currentPaneMembers(workspaceId, snapshot, latest, piTerminalIdsBySessionId) {
  if (!snapshot || !Array.isArray(snapshot.panes)) {
    throw new Error("Herdr membership snapshot is unavailable for recap grouping");
  }
  const agentsByPaneId = new Map((snapshot.agents ?? []).map((agent) => [agent.pane_id, agent]));
  const bySessionId = new Map();
  const byPaneId = new Map();
  const byTerminalId = new Map();
  for (const record of latest) {
    if (typeof record.source_id !== "string" || !record.source_id
      || typeof record.summary !== "string" || !record.summary.trim()
      || typeof record.record_id !== "string" || !record.record_id) continue;
    const existing = bySessionId.get(record.source_id);
    if (!existing || compareRecords(existing, record) <= 0) bySessionId.set(record.source_id, record);
    if (typeof record.pane_id === "string" && record.pane_id) {
      const paneRecord = byPaneId.get(record.pane_id);
      if (!paneRecord || compareRecords(paneRecord, record) <= 0) byPaneId.set(record.pane_id, record);
    }
    const terminalId = piTerminalIdsBySessionId?.[record.source_id];
    if (typeof terminalId === "string" && terminalId) {
      const terminalRecord = byTerminalId.get(terminalId);
      if (!terminalRecord || compareRecords(terminalRecord, record) <= 0) byTerminalId.set(terminalId, record);
    }
  }

  const members = [];
  const seenRecordIds = new Set();
  for (const pane of snapshot.panes) {
    if (pane?.workspace_id !== workspaceId || typeof pane.pane_id !== "string") continue;
    const agent = agentsByPaneId.get(pane.pane_id);
    const agentName = agent?.agent ?? pane.agent;
    if (agentName !== "pi") continue;
    const session = agent?.agent_session ?? pane.agent_session;
    const sessionId = session?.agent === "pi" && session.kind === "id" && typeof session.value === "string"
      ? session.value
      : null;
    const record = (sessionId ? bySessionId.get(sessionId) : null)
      ?? byPaneId.get(pane.pane_id)
      ?? byTerminalId.get(pane.terminal_id);
    if (!record || seenRecordIds.has(record.record_id)) continue;
    seenRecordIds.add(record.record_id);
    members.push(record);
  }
  return members.sort(compareRecords).map(groupMember);
}

async function createGroup(runRecap, dataRoot, sourceKind, sourceId, members) {
  const args = ["create", "--kind", "group", "--source-kind", sourceKind, "--source-id", sourceId];
  const output = await runRecap(args, `${JSON.stringify({ members })}\n`);
  if (!/^[0-9a-f]{32}$/.test(output)) {
    throw new Error("session-recap did not return a published record ID");
  }
  const latest = await readLatestRecapRecords(dataRoot, sourceKind);
  const published = latest.find((record) => record.source_id === sourceId && record.record_id === output);
  if (!published || typeof published.summary !== "string" || !published.summary.trim()) {
    throw new Error(`session-recap did not index a nonblank published ${sourceKind} recap`);
  }
  return output;
}

export async function reconcileRecapCoordinator({
  state,
  dataRoot,
  snapshot,
  now = Date.now(),
  runRecap = runSessionRecap,
  persist = async () => {},
  onError = (error, workspaceId) => console.warn(`[herdr-overview] recap grouping failed${workspaceId ? ` for ${workspaceId}` : ""}: ${error.message}`),
  resumeDeadlines = false,
} = {}) {
  const next = normalizedState(state);
  const processed = new Set(next.processedRecordIds);
  const publications = (await readAllRecapRecords(dataRoot))
    .filter((record) => record?.source_kind === "pi-session" && record.status === "published"
      && typeof record.record_id === "string" && record.record_id && !processed.has(record.record_id))
    .sort(compareRecords);
  const changedDeadlines = new Set();

  for (const record of publications) {
    processed.add(record.record_id);
    if (typeof record.workspace_id !== "string" || !record.workspace_id.trim()) continue;
    const deadline = publicationTime(record, now) + WORKSPACE_QUIET_PERIOD_MS;
    next.workspaceDeadlines[record.workspace_id] = new Date(deadline).toISOString();
    changedDeadlines.add(record.workspace_id);
  }
  next.processedRecordIds = [...processed];
  const latestPiRecaps = await readLatestRecapRecords(dataRoot, "pi-session");
  const currentSessions = new Set(latestPiRecaps
    .map((record) => record.source_id)
    .filter((sessionId) => typeof sessionId === "string" && sessionId));
  for (const sessionId of Object.keys(next.piTerminalIdsBySessionId)) {
    if (!currentSessions.has(sessionId)) delete next.piTerminalIdsBySessionId[sessionId];
  }
  if (Array.isArray(snapshot?.panes)) {
    const paneById = new Map(snapshot.panes.map((pane) => [pane.pane_id, pane]));
    for (const record of latestPiRecaps) {
      if (typeof record.source_id !== "string" || !record.source_id) continue;
      const pane = paneById.get(record.pane_id);
      if (typeof pane?.terminal_id === "string" && pane.terminal_id) {
        next.piTerminalIdsBySessionId[record.source_id] = pane.terminal_id;
      }
    }
  }
  await persist(next);

  const due = Object.entries(next.workspaceDeadlines)
    .filter(([, deadline]) => Date.parse(deadline) <= now)
    .sort(([leftId, leftDeadline], [rightId, rightDeadline]) => Date.parse(leftDeadline) - Date.parse(rightDeadline) || leftId.localeCompare(rightId));

  for (const [workspaceId] of due) {
    let members;
    try {
      members = await currentPaneMembers(workspaceId, snapshot, latestPiRecaps, next.piTerminalIdsBySessionId);
    } catch (error) {
      onError(error, workspaceId);
      continue;
    }
    if (!members.length) {
      delete next.workspaceDeadlines[workspaceId];
      await persist(next);
      continue;
    }

    try {
      await createGroup(runRecap, dataRoot, "workspace", workspaceId, members);
    } catch (error) {
      onError(error, workspaceId);
      continue;
    }

    delete next.workspaceDeadlines[workspaceId];
    await persist(next);

    const workspaceRecaps = await readLatestRecapRecords(dataRoot, "workspace");
    const sessionMembers = workspaceRecaps
      .filter((record) => typeof record.summary === "string" && record.summary.trim() && typeof record.record_id === "string")
      .sort((left, right) => String(left.source_id).localeCompare(String(right.source_id)))
      .map(groupMember);
    if (!sessionMembers.length) continue;
    try {
      await createGroup(runRecap, dataRoot, "herdr-session", "active", sessionMembers);
    } catch (error) {
      onError(error, "active");
    }
  }

  const wakeups = Object.entries(next.workspaceDeadlines)
    .filter(([, deadline]) => Date.parse(deadline) > now)
    .filter(([workspaceId]) => resumeDeadlines || changedDeadlines.has(workspaceId))
    .map(([workspaceId, deadline]) => ({ workspaceId, deadline }));

  return { state: next, wakeups };
}
