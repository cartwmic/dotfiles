import { spawn } from "node:child_process";
import os from "node:os";
import path from "node:path";
import { readAllRecapRecords, readCurrentPiPrompts, readLatestRecapRecords } from "./recap-store.mjs";

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
  const manualTerminalIdsBySourceId = {};
  if (value.manualTerminalIdsBySourceId && typeof value.manualTerminalIdsBySourceId === "object") {
    for (const [sourceId, terminalId] of Object.entries(value.manualTerminalIdsBySourceId)) {
      if (sourceId && typeof terminalId === "string" && terminalId) manualTerminalIdsBySourceId[sourceId] = terminalId;
    }
  }
  return { schema_version: 1, processedRecordIds, workspaceDeadlines, piTerminalIdsBySessionId, manualTerminalIdsBySourceId };
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

function setNewestRecord(recordsByKey, key, record) {
  if (typeof key !== "string" || !key) return;
  const existing = recordsByKey.get(key);
  if (!existing || compareRecords(existing, record) <= 0) recordsByKey.set(key, record);
}

async function currentPaneMembers(workspaceId, snapshot, latest, piTerminalIdsBySessionId, manualTerminalIdsBySourceId) {
  if (!snapshot || !Array.isArray(snapshot.panes)) {
    throw new Error("Herdr membership snapshot is unavailable for recap grouping");
  }
  const agentsByPaneId = new Map((snapshot.agents ?? []).map((agent) => [agent.pane_id, agent]));
  const piBySessionId = new Map();
  const piByPaneId = new Map();
  const piByTerminalId = new Map();
  const manualByPaneId = new Map();
  const manualByTerminalId = new Map();
  for (const record of latest) {
    if (typeof record.source_id !== "string" || !record.source_id
      || typeof record.summary !== "string" || !record.summary.trim()
      || typeof record.record_id !== "string" || !record.record_id) continue;
    if (record.source_kind === "pi-session") {
      setNewestRecord(piBySessionId, record.source_id, record);
      setNewestRecord(piByPaneId, record.pane_id, record);
      setNewestRecord(piByTerminalId, piTerminalIdsBySessionId?.[record.source_id], record);
    } else if (record.source_kind === "manual") {
      // Follow a source-attributed manual recap after pane.move only when its
      // terminal association was learned while that native pane ID was live.
      const terminalId = manualTerminalIdsBySourceId?.[record.source_id];
      if (terminalId) setNewestRecord(manualByTerminalId, terminalId, record);
      else setNewestRecord(manualByPaneId, record.source_id, record);
    }
  }

  const members = [];
  const seenRecordIds = new Set();
  for (const pane of snapshot.panes) {
    if (pane?.workspace_id !== workspaceId || typeof pane.pane_id !== "string") continue;
    const agent = agentsByPaneId.get(pane.pane_id);
    const session = agent?.agent_session ?? pane.agent_session;
    const sessionId = session?.agent === "pi" && session.kind === "id" && typeof session.value === "string"
      ? session.value
      : null;
    const piRecord = (sessionId ? piBySessionId.get(sessionId) : null)
      ?? piByPaneId.get(pane.pane_id)
      ?? piByTerminalId.get(pane.terminal_id);
    const manualRecord = manualByTerminalId.get(pane.terminal_id) ?? manualByPaneId.get(pane.pane_id);
    const record = [piRecord, manualRecord].filter(Boolean).sort(compareRecords).at(-1);
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
  const latestRecaps = await readLatestRecapRecords(dataRoot);
  const latestPiRecaps = latestRecaps.filter((record) => record.source_kind === "pi-session");
  const latestManualRecaps = latestRecaps.filter((record) => record.source_kind === "manual"
    && typeof record.source_id === "string" && record.source_id);
  const currentManualSourceIds = new Set(latestManualRecaps.map((record) => record.source_id));
  for (const sourceId of Object.keys(next.manualTerminalIdsBySourceId)) {
    if (!currentManualSourceIds.has(sourceId)) delete next.manualTerminalIdsBySourceId[sourceId];
  }
  const prompts = await readCurrentPiPrompts(dataRoot);
  const currentSessions = new Set([...latestPiRecaps.map((record) => record.source_id),
    ...prompts.map((prompt) => prompt.session_id)]
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
    for (const prompt of prompts) {
      const pane = paneById.get(prompt.pane_id);
      if (typeof pane?.terminal_id === "string" && pane.terminal_id) {
        next.piTerminalIdsBySessionId[prompt.session_id] = pane.terminal_id;
      }
    }
    for (const record of latestManualRecaps) {
      // Manual --source-id is intentionally immutable. Persist an association
      // only while that exact source ID resolves to a live native pane.
      if (next.manualTerminalIdsBySourceId[record.source_id]) continue;
      const pane = paneById.get(record.source_id);
      if (typeof pane?.terminal_id === "string" && pane.terminal_id) {
        next.manualTerminalIdsBySourceId[record.source_id] = pane.terminal_id;
      }
    }
  }
  await persist(next);

  const due = Object.entries(next.workspaceDeadlines)
    .filter(([, deadline]) => Date.parse(deadline) <= now)
    .sort(([leftId, leftDeadline], [rightId, rightDeadline]) => Date.parse(leftDeadline) - Date.parse(rightDeadline) || leftId.localeCompare(rightId));
  const needsWakeup = Object.entries(next.workspaceDeadlines)
    .some(([workspaceId, deadline]) => Date.parse(deadline) > now && (resumeDeadlines || changedDeadlines.has(workspaceId)));
  if (due.length || needsWakeup) {
    let autoPublish;
    try {
      autoPublish = await runRecap(["config", "auto-publish"]);
    } catch (error) {
      onError(error);
      return { state: next, wakeups: [] };
    }
    if (autoPublish === "disabled") return { state: next, wakeups: [] };
    if (autoPublish !== "enabled") {
      onError(new Error("session-recap returned an invalid auto-publish policy"));
      return { state: next, wakeups: [] };
    }
  }

  for (const [workspaceId] of due) {
    let members;
    try {
      members = await currentPaneMembers(
        workspaceId, snapshot, latestRecaps, next.piTerminalIdsBySessionId, next.manualTerminalIdsBySourceId,
      );
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

    if (!Array.isArray(snapshot?.workspaces)) {
      onError(new Error("Herdr workspace snapshot is unavailable for session recap grouping"), "active");
      continue;
    }
    const currentWorkspaceIds = new Set(snapshot.workspaces
      .map((workspace) => workspace?.workspace_id)
      .filter((workspaceId) => typeof workspaceId === "string" && workspaceId));
    const workspaceRecaps = await readLatestRecapRecords(dataRoot, "workspace");
    const sessionMembers = workspaceRecaps
      .filter((record) => currentWorkspaceIds.has(record.source_id)
        && typeof record.summary === "string" && record.summary.trim()
        && typeof record.record_id === "string")
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
