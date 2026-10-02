import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { randomUUID } from "node:crypto";
import { currentPaneForCaller, invokeOverviewReconcile, runSessionRecap } from "./helpers.ts";
import { readPrompt, writePrompt } from "./prompt-store.ts";

function identity(ctx: ExtensionContext): string | undefined {
  const id = ctx.sessionManager.getSessionId();
  return typeof id === "string" && id.trim() ? id : undefined;
}
function warn(message: string) { console.warn(`[herdr-overview] ${message}`); }

export function registerHerdrOverviewExtension(pi: ExtensionAPI): void {
  let active: string | undefined;
  let epoch = 0;
  let queue = Promise.resolve();
  const enqueue = (task: () => Promise<void>) => {
    queue = queue.then(task).catch(() => warn("overview update failed; saved recaps remain available for recovery"));
    return queue;
  };
  const membership = () => currentPaneForCaller(process.env.HERDR_SOCKET_PATH?.trim() || undefined, process.env.HERDR_PANE_ID?.trim() || undefined);

  async function consume(sessionId: string, generation: number, recordId?: string) {
    const records = recordId
      ? [JSON.parse(await runSessionRecap(["read", recordId, "--json"])).record]
      : JSON.parse(await runSessionRecap(["list", "--json", "--source-kind", "pi", "--status", "published"])).records;
    for (const record of records) {
      const owner = record.metadata?.pi?.sessionId ?? record.metadata?.pi?.nativeSessionId;
      if (record.status !== "published" || owner !== sessionId) continue;
      if (active !== sessionId || epoch !== generation) return;
      const pane = await membership();
      if (active !== sessionId || epoch !== generation) return;
      const prompt = readPrompt(sessionId);
      if (prompt) writePrompt({ ...prompt, pane_id: pane?.paneId });
      // Attribution is immutable once recorded. Return/startup may retry a missed wake-up,
      // but must not move the publication's quiet deadline to a different workspace.
      if (!Object.hasOwn(record.annotations ?? {}, "herdr")) {
        await runSessionRecap(["annotate", record.record_id, "--namespace", "herdr", "--metadata-json", JSON.stringify({
          ...(pane ? { pane_id: pane.paneId, ...(pane.workspaceId ? { workspace_id: pane.workspaceId } : {}) } : {}),
        })]);
      }
      if (process.env.HERDR_SOCKET_PATH?.trim()) {
        try { await invokeOverviewReconcile(process.env.HERDR_SOCKET_PATH.trim()); }
        catch { warn("saved recap annotation retained; overview wake-up failed"); }
      }
    }
  }

  pi.on("session_start", (_event, ctx) => {
    active = identity(ctx);
    const generation = ++epoch;
    const sessionId = active;
    if (!sessionId) return;
    return enqueue(async () => {
      const pane = await membership();
      if (active !== sessionId || epoch !== generation) return;
      const prompt = readPrompt(sessionId);
      if (prompt) writePrompt({ ...prompt, pane_id: pane?.paneId });
      await consume(sessionId, generation);
    });
  });
  pi.on("session_shutdown", () => { active = undefined; epoch++; });
  pi.events.on("recap:saved", (event: any) => {
    if (typeof event?.recordId !== "string" || event.sessionId !== active || !active) return;
    const sessionId = active;
    const generation = epoch;
    void enqueue(() => consume(sessionId, generation, event.recordId));
  });

  pi.on("input", async (event, ctx) => {
    if (!((event.source === "interactive" && ctx.mode === "tui") || (event.source === "rpc" && ctx.mode === "rpc")) || !event.text.trim()) return { action: "continue" };
    const sessionId = identity(ctx);
    if (!sessionId) return { action: "continue" };
    const generation = epoch;
    const prompt = { schema_version: 1, prompt_id: randomUUID(), session_id: sessionId, text: event.text, working: true, captured_at: new Date().toISOString() };
    // Persist before the socket await; a newer input must never be overwritten.
    writePrompt(prompt);
    const pane = await membership();
    if (active === sessionId && epoch === generation && readPrompt(sessionId)?.prompt_id === prompt.prompt_id) writePrompt({ ...readPrompt(sessionId), pane_id: pane?.paneId });
    return { action: "continue" };
  });
  pi.on("agent_settled", async (_event, ctx) => {
    if (!ctx.isIdle()) return;
    const sessionId = identity(ctx);
    if (!sessionId) return;
    const generation = epoch;
    const prompt = readPrompt(sessionId);
    if (!prompt?.working) return;
    writePrompt({ ...prompt, working: false });
    const pane = await membership();
    if (active === sessionId && epoch === generation && readPrompt(sessionId)?.prompt_id === prompt.prompt_id) writePrompt({ ...readPrompt(sessionId), pane_id: pane?.paneId });
  });
}
export default registerHerdrOverviewExtension;
