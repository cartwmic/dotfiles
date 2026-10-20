// notify-owner: the one explicit way a Pi worker rings the owner's doorbell.
//
// A worker that needs the owner calls the `notify_owner` tool; an `ask_user_question` dialog
// rings too; a clean Pi exit in a Herdr pane reports `exited`. Each runs `agent-alert emit` for
// this pane. Nothing is inferred from status, labels or screen text, and a plain finished turn
// does not ring.
//
// Kept free of Pi imports so node --test can run it. index.ts wires it to Pi.
import { spawn } from "node:child_process";
import { accessSync, appendFileSync, constants, mkdirSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

export const TOOL_NAME = "notify_owner";
export const ASK_TOOL_NAME = "ask_user_question";
const CORE_RELATIVE = ".local/share/agent-alert/core/agent-alert";
const LOG_RELATIVE = ".local/state/agent-alert/agent-alert.log";

type Env = Record<string, string | undefined>;
type Child = { on(event: string, handler: (arg?: unknown) => void): unknown; unref(): void };
type Spawner = (command: string, args: string[], options: Record<string, unknown>) => Child;
export type Kind = "question" | "exited";

/** A subagent child has no owner to ring (its supervisor answers it), and outside Herdr there is no pane to name. */
export function eligible(env: Env): boolean {
  return env.PI_SUBAGENT_CHILD !== "1" && Boolean(env.HERDR_PANE_ID?.trim());
}

export function corePath(env: Env): string {
  return join(env.HOME || homedir(), CORE_RELATIVE);
}

// Only "~" and "~/..." (the core also expands "~user/...", which nobody sets here).
const expand = (path: string, home: string) => (path === "~" || path.startsWith("~/") ? join(home, path.slice(1)) : path);

/** The operator log path, resolved as the core does: AGENT_ALERT_LOG, then log_path in the config file, then the default. */
export function logPath(env: Env): string {
  const home = env.HOME || homedir();
  if (env.AGENT_ALERT_LOG) return expand(env.AGENT_ALERT_LOG, home);
  try {
    const config = JSON.parse(readFileSync(expand(env.AGENT_ALERT_CONFIG || "~/.config/agent-alert/config.json", home), "utf8"));
    if (typeof config?.log_path === "string" && config.log_path) return expand(config.log_path, home);
  } catch {
    // no config, or not JSON: the default
  }
  return join(home, LOG_RELATIVE);
}

/** The agent-alert operator log, where the core and the sinks already write their problems. */
function logProblem(env: Env, message: string): void {
  try {
    const path = logPath(env);
    mkdirSync(dirname(path), { recursive: true });
    appendFileSync(path, `${new Date().toISOString().replace(/\.\d+Z$/, "Z")} notify-owner: ${message}\n`);
  } catch {
    // best effort
  }
}

/**
 * Start `agent-alert emit` for this pane and do not wait for it (the core waits on the sink, up to its bound).
 * "sent" means the command was started; a failure to start it or a nonzero exit is logged to the operator log.
 */
export function ring(env: Env, kind: Kind = "question", spawnFn: Spawner = spawn as unknown as Spawner): "sent" | "no-core" | "no-pane" {
  const pane = env.HERDR_PANE_ID?.trim();
  if (!pane) return "no-pane";
  const core = corePath(env);
  try {
    accessSync(core, constants.X_OK);
  } catch {
    return "no-core";
  }
  const args = ["emit", "--worker", pane, "--kind", kind, "--context", "agent=pi"];
  if (env.HERDR_WORKSPACE_ID?.trim()) args.push("--context", `workspace_id=${env.HERDR_WORKSPACE_ID.trim()}`);
  const child = spawnFn(core, args, { detached: true, stdio: "ignore", env });
  child.on("error", (error) => logProblem(env, `cannot start agent-alert emit (${kind}): ${(error as Error)?.message ?? error}`));
  child.on("exit", (code) => {
    if (code !== 0) logProblem(env, `agent-alert emit (${kind}) exited with status ${code}; the event was not recorded`);
  });
  child.unref();
  return "sent";
}

const text = (message: string, isError = false) => ({ content: [{ type: "text" as const, text: message }], details: {}, ...(isError ? { isError: true } : {}) });

export interface PiLike {
  registerTool(tool: Record<string, unknown>): void;
  on(event: string, handler: (event: { toolName?: string; reason?: string }, ctx: { hasUI?: boolean; mode?: string }) => void): void;
}

/** Register the tool and the listeners. `Type` is TypeBox's, passed in so tests need no Pi. */
export function registerNotifyOwner(pi: PiLike, Type: { Object(p: unknown): unknown; String(o?: unknown): unknown }, env: Env = process.env, spawnFn?: Spawner): void {
  if (!eligible(env)) return;
  pi.registerTool({
    name: TOOL_NAME,
    label: "Notify Owner",
    description:
      "Ring the owner's doorbell because you need their answer or decision, or because you have answered a question " +
      "they or the coordinator asked you (summary like 'answer ready: <topic>'). It returns at once and does not wait: " +
      "put the same text in your reply and end your turn. Never for progress or for finishing a turn nobody is waiting on, " +
      "and not for a question you are asking with ask_user_question (that rings by itself).",
    promptSnippet: "Ring the owner's doorbell when you need their answer or decision, or when you have answered a question they asked",
    parameters: Type.Object({ question: Type.String({ description: "The question, or the one-line answer summary. It stays in your transcript; the doorbell sends no text." }) }),
    async execute() {
      const result = ring(env, "question", spawnFn);
      if (result === "sent") return text("Doorbell dispatched. Put the question or answer summary in your reply and end your turn; do not wait. (A failure to deliver is logged, not shown here.)");
      return text(`Owner not notified (${result === "no-core" ? "agent-alert is not installed or not executable on this machine" : "this is not a Herdr pane"}). Put the question or answer summary in your reply anyway.`, true);
    },
  });
  pi.on("tool_execution_start", (event, ctx) => {
    if (event.toolName === ASK_TOOL_NAME && ctx.hasUI) ring(env, "question", spawnFn);
  });
  // A clean Pi exit, including SIGTERM and SIGHUP (closing the pane). Reload, new, resume and fork also
  // shut a session down but Pi keeps running, so only "quit" counts. Only the interactive TUI is a pane's agent: a
  // print-mode run (no UI) or an RPC helper (hasUI is true there too) that inherited the pane id is not.
  pi.on("session_shutdown", (event, ctx) => {
    let tui = false;
    try {
      tui = ctx.mode === "tui";
    } catch {
      // a stale ctx: treat as not an interactive pane
    }
    if (event.reason === "quit" && tui) ring(env, "exited", spawnFn);
  });
}
