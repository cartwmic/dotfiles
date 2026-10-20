// notify-owner: the one explicit way a Pi worker rings the owner's doorbell.
//
// A worker that needs the owner calls the `notify_owner` tool; an `ask_user_question` dialog
// rings too; a clean Pi exit in a Herdr pane reports `exited`. Each runs `agent-alert emit` for
// this pane. Nothing is inferred from status, labels or screen text, and a plain finished turn
// does not ring.
//
// Kept free of Pi imports so node --test can run it. index.ts wires it to Pi.
import { spawn } from "node:child_process";
import { accessSync, appendFileSync, constants, mkdirSync } from "node:fs";
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

/** The agent-alert operator log, where the core and the sinks already write their problems. */
function logProblem(env: Env, message: string): void {
  try {
    const path = env.AGENT_ALERT_LOG || join(env.HOME || homedir(), LOG_RELATIVE);
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
  on(event: string, handler: (event: { toolName?: string; reason?: string }, ctx: { hasUI?: boolean }) => void): void;
}

/** Register the tool and the listeners. `Type` is TypeBox's, passed in so tests need no Pi. */
export function registerNotifyOwner(pi: PiLike, Type: { Object(p: unknown): unknown; String(o?: unknown): unknown }, env: Env = process.env, spawnFn?: Spawner): void {
  if (!eligible(env)) return;
  pi.registerTool({
    name: TOOL_NAME,
    label: "Notify Owner",
    description:
      "Ring the owner's doorbell because you need their answer or decision. It returns at once and does not wait: " +
      "state the question in your reply and end your turn. Call it only when you cannot go on without the owner, " +
      "never for progress or for finishing, and not for a question you are asking with ask_user_question (that rings by itself).",
    promptSnippet: "Ring the owner's doorbell when you need their answer or decision",
    parameters: Type.Object({ question: Type.String({ description: "The question, in one short sentence. It stays in your transcript; the doorbell sends no text." }) }),
    async execute() {
      const result = ring(env, "question", spawnFn);
      if (result === "sent") return text("Doorbell dispatched. Ask the question in your reply and end your turn; do not wait. (A failure to deliver is logged, not shown here.)");
      return text(`Owner not notified (${result === "no-core" ? "agent-alert is not installed or not executable on this machine" : "this is not a Herdr pane"}). Ask the question in your reply anyway.`, true);
    },
  });
  pi.on("tool_execution_start", (event, ctx) => {
    if (event.toolName === ASK_TOOL_NAME && ctx.hasUI) ring(env, "question", spawnFn);
  });
  // A clean Pi exit, including SIGTERM and SIGHUP (closing the pane). Reload, new, resume and fork also
  // shut a session down but Pi keeps running, so only "quit" counts. A print-mode run has no UI and is not a pane's agent.
  pi.on("session_shutdown", (event, ctx) => {
    let ui = false;
    try {
      ui = ctx.hasUI === true;
    } catch {
      // a stale ctx: treat as not an interactive pane
    }
    if (event.reason === "quit" && ui) ring(env, "exited", spawnFn);
  });
}
