import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { HerdrApi } from "./herdr-api.mjs";
import { readState } from "./state-store.mjs";

const ENTRYPOINT = fileURLToPath(new URL("../index.mjs", import.meta.url));

export function scheduleDeadlineWakeup({ stateDir, workspaceId, deadline, socketPath, env = process.env }) {
  if (!socketPath) return null;
  const child = spawn(process.execPath, [ENTRYPOINT, "deadline-wakeup", workspaceId, deadline, stateDir, socketPath], {
    detached: true,
    stdio: "ignore",
    env: { ...env, HERDR_SOCKET_PATH: socketPath, HERDR_PLUGIN_STATE_DIR: stateDir },
  });
  child.once("error", (error) => console.error(`[herdr-overview] could not start recap deadline wake-up: ${error.message}`));
  child.unref();
  return child.pid ?? null;
}

export async function runDeadlineWakeup({ workspaceId, deadline, stateDir, socketPath, api = null, now = Date.now }) {
  const target = Date.parse(deadline);
  if (!Number.isFinite(target)) throw new Error("invalid recap deadline");
  const isCurrent = async () => {
    const state = await readState(stateDir);
    return state.recapCoordinator?.workspaceDeadlines?.[workspaceId] === new Date(target).toISOString();
  };
  if (!await isCurrent()) return false;

  const delayMs = target - now();
  if (delayMs > 0) await new Promise((resolve) => setTimeout(resolve, delayMs));
  if (!await isCurrent()) return false;
  if (!socketPath) throw new Error("HERDR_SOCKET_PATH is required for a recap deadline wake-up");
  const herdrApi = api ?? new HerdrApi({ socketPath, timeoutMs: 6 * 60 * 1_000 });
  await herdrApi.request("plugin.action.invoke", { action_id: "overview.reconcile" });
  return true;
}
