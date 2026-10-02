import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';

export const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export function piSessionsDirectory(env = process.env) {
  return env.HERDR_OVERVIEW_PI_SESSIONS_DIR || path.join(env.XDG_STATE_HOME || path.join(env.HOME, '.local/state'), 'herdr-overview', 'pi-sessions');
}
export function piSessionFile(socketPath, terminalId, env = process.env) {
  return path.join(piSessionsDirectory(env), createHash('sha256').update(JSON.stringify([socketPath, terminalId])).digest('hex') + '.json');
}
function read(file) { try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return null; } }
function alive(pid) { if (!Number.isInteger(pid) || pid <= 0) return false; try { process.kill(pid, 0); return true; } catch { return false; } }
function digest(sessionId, env) {
  const file = path.join(env.PI_SESSION_SEARCH_DIGEST_DIR || path.join(env.HOME, '.pi/session-search/digests'), sessionId + '.json');
  const value = read(file);
  if (!value) return { status: 'unavailable', body: null, generatedAt: null, reason: 'missing' };
  if (value.schemaVersion !== 1 || typeof value.body !== 'string' || !value.body.trim() || typeof value.generatedAt !== 'string' || !/^\d{4}-\d{2}-\d{2}T/.test(value.generatedAt) || !Number.isFinite(Date.parse(value.generatedAt))) return { status: 'unavailable', body: null, generatedAt: null, reason: 'invalid' };
  return { status: 'available', body: value.body, generatedAt: value.generatedAt, reason: null };
}

// Native agent detection is deliberately not part of this association.
export function readPiSessionFields(snapshot, { socketPath, env = process.env } = {}) {
  const piSessionsByPaneId = {};
  if (!socketPath || snapshot?.protocol !== 22) return { piSessionsByPaneId };
  let files; try { files = fs.readdirSync(piSessionsDirectory(env)); } catch { return { piSessionsByPaneId }; }
  const records = files.filter(file => file.endsWith('.json')).map(file => read(path.join(piSessionsDirectory(env), file))).filter(record => record?.socketPath === socketPath);
  for (const pane of snapshot.panes ?? []) {
    if (typeof pane.terminal_id !== 'string' || !pane.terminal_id) continue;
    if (snapshot.panes.filter(other => other.terminal_id === pane.terminal_id).length !== 1) continue;
    const matches = records.filter(record => record.terminalId === pane.terminal_id);
    if (matches.length !== 1) continue;
    const record = matches[0];
    if (record.schemaVersion !== 1 || !UUID.test(record.sessionId ?? '') || typeof record.paneId !== 'string' || !record.paneId || typeof record.generation !== 'string' || !record.generation || !alive(record.publisherPid) || !(record.sessionName === null || typeof record.sessionName === 'string')) continue;
    const nativeSessions = [pane.agent_session, ...(snapshot.agents ?? []).filter(agent => agent.pane_id === pane.pane_id).map(agent => agent.agent_session)].filter(id => id !== null && id !== undefined);
    if (nativeSessions.some(id => typeof id !== 'object' || id.agent !== 'pi' || id.kind !== 'id' || id.value !== record.sessionId)) continue;
    piSessionsByPaneId[pane.pane_id] = { sessionId: record.sessionId, sessionName: record.sessionName, digest: digest(record.sessionId, env) };
  }
  return { piSessionsByPaneId };
}
