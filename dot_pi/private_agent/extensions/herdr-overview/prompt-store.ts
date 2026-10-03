import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { homedir } from "node:os";
import path from "node:path";

function directory() {
  return path.join(process.env.XDG_DATA_HOME || path.join(homedir(), ".local", "share"), "herdr-overview", "prompts");
}
function filename(sessionId: string) { return path.join(directory(), `${encodeURIComponent(sessionId).replace(/[!'()*]/g, c => `%${c.charCodeAt(0).toString(16).toUpperCase()}`)}.json`); }
export function readPrompt(sessionId: string): any {
  try { return JSON.parse(readFileSync(filename(sessionId), "utf8")); } catch { return undefined; }
}
export function writePrompt(prompt: any): void {
  mkdirSync(directory(), { recursive: true, mode: 0o700 });
  const file = filename(prompt.session_id);
  const temporary = `${file}.${randomUUID()}.tmp`;
  writeFileSync(temporary, JSON.stringify(prompt), { mode: 0o600 });
  renameSync(temporary, file);
}
