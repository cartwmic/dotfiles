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

export async function readRecapFields(snapshot, root = sessionRecapDataRoot()) {
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
  try {
    const promptFiles = await readdir(path.join(root, "prompts"), { withFileTypes: true });
    for (const entry of promptFiles) {
      if (!entry.isFile() || !entry.name.endsWith(".json")) continue;
      const prompt = await readJson(path.join(root, "prompts", entry.name));
      if (prompt?.schema_version !== 1 || typeof prompt.session_id !== "string") continue;
      promptsBySessionId[prompt.session_id] = prompt;
      if (typeof prompt.pane_id === "string") promptsByPaneId[prompt.pane_id] = prompt;
    }
  } catch {
    // Current prompts are optional; the live Herdr model remains complete without them.
  }

  const piRecapsBySessionId = {};
  const piRecapsByPaneId = {};
  const piSources = sources.filter((item) => item?.source_kind === "pi-session" && typeof item.source_id === "string");
  const recapReads = await Promise.all(piSources.map(async (item) => ({
    sessionId: item.source_id,
    recap: await bySource("pi-session", item.source_id),
  })));
  for (const { sessionId, recap } of recapReads) {
    piRecapsBySessionId[sessionId] = recap;
    const paneId = recap.lastAttempt?.pane_id ?? recap.latest?.pane_id;
    if (!paneId) continue;
    const existing = piRecapsByPaneId[paneId];
    const dateOf = (value) => value?.lastAttempt?.created_at ?? value?.latest?.published_at ?? "";
    if (!existing || dateOf(recap) >= dateOf(existing)) piRecapsByPaneId[paneId] = recap;
  }

  const workspaceRecaps = {};
  for (const workspace of snapshot.workspaces ?? []) {
    workspaceRecaps[`workspace:${workspace.workspace_id}`] = await bySource("workspace", workspace.workspace_id);
  }

  return {
    promptsByPaneId,
    promptsBySessionId,
    piRecapsByPaneId,
    piRecapsBySessionId,
    workspaceRecaps,
    sessionRecap: await bySource("herdr-session", "active"),
  };
}
