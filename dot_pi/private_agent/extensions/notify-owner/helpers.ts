// notify-owner: the one explicit way a Pi worker rings the owner's doorbell.
//
// A worker that needs the owner calls the `notify_owner` tool; an `ask_user_question` dialog
// rings too. Both run `agent-alert emit --kind question` for this pane. Nothing is inferred
// from status, labels or screen text, and a plain finished turn does not ring.
//
// Kept free of Pi imports so node --test can run it. index.ts wires it to Pi.
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

export const TOOL_NAME = "notify_owner";
export const ASK_TOOL_NAME = "ask_user_question";
const CORE_RELATIVE = ".local/share/agent-alert/core/agent-alert";

type Env = Record<string, string | undefined>;
type Spawner = (command: string, args: string[], options: Record<string, unknown>) => { on(event: string, handler: () => void): unknown; unref(): void };

/** A subagent child has no owner to ring (its supervisor answers it), and outside Herdr there is no pane to name. */
export function eligible(env: Env): boolean {
  return env.PI_SUBAGENT_CHILD !== "1" && Boolean(env.HERDR_PANE_ID?.trim());
}

export function corePath(env: Env): string {
  return join(env.HOME || homedir(), CORE_RELATIVE);
}

/** Start `agent-alert emit` for this pane and do not wait for it (the core waits on the sink, up to its bound). */
export function ring(env: Env, spawnFn: Spawner = spawn as unknown as Spawner): "sent" | "no-core" | "no-pane" {
  const pane = env.HERDR_PANE_ID?.trim();
  if (!pane) return "no-pane";
  const core = corePath(env);
  if (!existsSync(core)) return "no-core";
  const args = ["emit", "--worker", pane, "--kind", "question", "--context", "agent=pi"];
  if (env.HERDR_WORKSPACE_ID?.trim()) args.push("--context", `workspace_id=${env.HERDR_WORKSPACE_ID.trim()}`);
  const child = spawnFn(core, args, { detached: true, stdio: "ignore", env });
  child.on("error", () => {}); // best effort: the inbox write is the core's job, the ring is a nudge
  child.unref();
  return "sent";
}

const text = (message: string, isError = false) => ({ content: [{ type: "text" as const, text: message }], details: {}, ...(isError ? { isError: true } : {}) });

export interface PiLike {
  registerTool(tool: Record<string, unknown>): void;
  on(event: string, handler: (event: { toolName?: string }, ctx: { hasUI?: boolean }) => void): void;
}

/** Register the tool and the ask_user_question listener. `Type` is TypeBox's, passed in so tests need no Pi. */
export function registerNotifyOwner(pi: PiLike, Type: { Object(p: unknown): unknown; String(o?: unknown): unknown }, env: Env = process.env, spawnFn?: Spawner): void {
  if (!eligible(env)) return;
  pi.registerTool({
    name: TOOL_NAME,
    label: "Notify Owner",
    description:
      "Ring the owner's doorbell because you need their answer or decision. It returns at once and does not wait: " +
      "state the question in your reply and end your turn. Call it only when you cannot go on without the owner, " +
      "never for progress or for finishing.",
    promptSnippet: "Ring the owner's doorbell when you need their answer or decision",
    parameters: Type.Object({ question: Type.String({ description: "The question, in one short sentence. It stays in your transcript; the doorbell sends no text." }) }),
    async execute() {
      const result = ring(env, spawnFn);
      if (result === "sent") return text("Owner notified. Ask the question in your reply and end your turn; do not wait.");
      return text(`Owner not notified (${result === "no-core" ? "agent-alert is not installed on this machine" : "this is not a Herdr pane"}). Ask the question in your reply anyway.`, true);
    },
  });
  pi.on("tool_execution_start", (event, ctx) => {
    if (event.toolName === ASK_TOOL_NAME && ctx.hasUI) ring(env, spawnFn);
  });
}
