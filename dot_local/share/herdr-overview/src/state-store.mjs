import { mkdir, open, readFile, rename, rm, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import { randomUUID } from "node:crypto";

export function overviewStateDir(env = process.env) {
  if (env.HERDR_PLUGIN_STATE_DIR) return env.HERDR_PLUGIN_STATE_DIR;
  return path.join(env.XDG_STATE_HOME || path.join(os.homedir(), ".local", "state"), "herdr-overview");
}

export async function readState(stateDir) {
  try {
    const state = JSON.parse(await readFile(path.join(stateDir, "overview.json"), "utf8"));
    return state && typeof state === "object" ? state : {};
  } catch {
    return {};
  }
}

export async function writeState(stateDir, value) {
  await mkdir(stateDir, { recursive: true });
  const target = path.join(stateDir, "overview.json");
  const temporary = `${target}.${process.pid}.${randomUUID()}.tmp`;
  await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
  await rename(temporary, target);
}

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const LOCK_STALE_AFTER_MS = 10 * 60_000;

function processIsRunning(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error.code === "EPERM";
  }
}

export async function withStateLock(stateDir, callback) {
  await mkdir(stateDir, { recursive: true });
  const lockPath = path.join(stateDir, ".overview.lock");
  let handle;
  for (let attempt = 0; attempt < 120; attempt += 1) {
    try {
      handle = await open(lockPath, "wx", 0o600);
      break;
    } catch (error) {
      if (error.code !== "EEXIST") throw error;
      try {
        const lockStat = await stat(lockPath);
        const age = Date.now() - lockStat.mtimeMs;
        if (age > 30_000) {
          let ownerPid = null;
          try { ownerPid = Number((await readFile(lockPath, "utf8")).trim()); } catch { /* The lock owner may be writing it. */ }
          if (!processIsRunning(ownerPid) || age > LOCK_STALE_AFTER_MS) await rm(lockPath, { force: true });
        }
      } catch {
        // Another process may have released the lock between stat and rm.
      }
      await delay(50);
    }
  }
  if (!handle) throw new Error("timed out waiting for the overview state lock");
  try {
    await handle.writeFile(`${process.pid}\n`);
    return await callback();
  } finally {
    await handle.close();
    await rm(lockPath, { force: true });
  }
}
