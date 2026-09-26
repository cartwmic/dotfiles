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
  return { schema_version: 1, processedRecordIds, workspaceDeadlines };
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

async function currentPaneMembers(dataRoot, workspaceId) {
  const latest = await readLatestRecapRecords(dataRoot, "pi-session");
  const byPaneId = new Map();
  for (const record of latest) {
    if (typeof record.pane_id !== "string" || !record.pane_id
      || typeof record.summary !== "string" || !record.summary.trim() || typeof record.record_id !== "string") continue;
    const existing = byPaneId.get(record.pane_id);
    if (!existing || compareRecords(existing, record) <= 0) byPaneId.set(record.pane_id, record);
  }
  return [...byPaneId.values()]
    .filter((record) => record.workspace_id === workspaceId)
    .sort(compareRecords)
    .map(groupMember);
}

async function createGroup(runRecap, dataRoot, sourceKind, sourceId, members) {
  const args = ["create", "--kind", "group", "--source-kind", sourceKind, "--source-id", sourceId];
  const output = await runRecap(args, `${JSON.stringify({ members })}\n`);
  if (!/^[0-9a-f]{32}$/.test(output)) {
    throw new Error("session-recap did not return a published record ID");
  }
  const latest = await readLatestRecapRecords(dataRoot, sourceKind);
  if (!latest.some((record) => record.source_id === sourceId && record.record_id === output)) {
    throw new Error(`session-recap did not index the published ${sourceKind} recap`);
  }
  return output;
}

export async function reconcileRecapCoordinator({
  state,
  dataRoot,
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
  await persist(next);

  const due = Object.entries(next.workspaceDeadlines)
    .filter(([, deadline]) => Date.parse(deadline) <= now)
    .sort(([leftId, leftDeadline], [rightId, rightDeadline]) => Date.parse(leftDeadline) - Date.parse(rightDeadline) || leftId.localeCompare(rightId));

  for (const [workspaceId] of due) {
    const members = await currentPaneMembers(dataRoot, workspaceId);
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
