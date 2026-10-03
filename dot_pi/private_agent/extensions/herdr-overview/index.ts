import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { randomUUID } from "node:crypto";
import {
  currentPaneForCaller, exactTerminalForCaller, writePiMetadata, retirePiMetadata,
  invokeOverviewReconcile, invokeOverviewNameRefresh, runSessionRecap,
} from "./helpers.ts";
import { readPrompt, writePrompt } from "./prompt-store.ts";
import { registerQuestionWait } from "./question-wait.ts";

function identity(ctx: ExtensionContext): string | undefined {
  const id = ctx.sessionManager.getSessionId();
  return typeof id === "string" && id.trim() ? id : undefined;
}
function warn(message: string) { console.warn(`[herdr-overview] ${message}`); }
const pause = (ms: number) => new Promise(resolve => setTimeout(resolve, ms).unref?.());
// Herdr caps concurrent plugin commands (32). A session reload fans out many
// wake-ups at once, so a full slot table is retried briefly rather than reported.
async function invokeWithRetry(call: () => Promise<unknown>): Promise<void> {
  for (let attempt = 0; ; attempt++) {
    try { await call(); return; }
    catch (error) {
      if (attempt >= 3 || !/maximum concurrent plugin commands/.test(String((error as Error)?.message))) throw error;
      await pause(500 * 2 ** attempt);
    }
  }
}

export function registerHerdrOverviewExtension(pi: ExtensionAPI): void {
  registerQuestionWait(pi);
  let active: string | undefined;
  let epoch = 0;
  let queue = Promise.resolve();
  const enqueue = (task: () => Promise<void>) => {
    queue = queue.then(task).catch(() => warn("overview update failed; saved recaps remain available for recovery"));
    return queue;
  };
  const membership = () => currentPaneForCaller(process.env.HERDR_SOCKET_PATH?.trim() || undefined, process.env.HERDR_PANE_ID?.trim() || undefined);

	let generation = randomUUID();
	let metadataFile: string | undefined;
	let revision = 0;
	const retire = () => {
		revision++;
		retirePiMetadata(metadataFile, generation);
		metadataFile = undefined;
		generation = randomUUID();
	};
	const refreshMetadata = async (_event: unknown, ctx: ExtensionContext) => {
		if (ctx.mode !== "tui" && ctx.mode !== "rpc") return;
		// Capture plain public values before any await; never retain a session context.
		const sessionId = identity(ctx);
		const sessionName = ctx.sessionManager.getSessionName?.() || null;
		const socketPath = process.env.HERDR_SOCKET_PATH;
		const callerPaneId = process.env.HERDR_PANE_ID?.trim();
		const currentRevision = ++revision;
		const token = generation;
		if (!sessionId || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(sessionId) || !socketPath || !callerPaneId) {
			retirePiMetadata(metadataFile, generation); metadataFile = undefined; return;
		}
		const pane = await exactTerminalForCaller(socketPath, callerPaneId);
		if (currentRevision !== revision || token !== generation) return;
		if (!pane?.terminalId) { retirePiMetadata(metadataFile, generation); metadataFile = undefined; return; }
		const file = writePiMetadata({ schemaVersion: 1, socketPath, terminalId: pane.terminalId, paneId: pane.paneId, sessionId, sessionName, publisherPid: process.pid, generation });
		if (metadataFile !== file) retirePiMetadata(metadataFile, generation);
		metadataFile = file;
	};
	pi.on("session_start", (event, ctx) => { if (ctx.mode !== "tui" && ctx.mode !== "rpc") return; retire(); return refreshMetadata(event, ctx); });
	pi.on("session_shutdown", (_event, ctx) => { if (ctx.mode !== "tui" && ctx.mode !== "rpc") return; retire(); });
	pi.on("session_info_changed", async (event, ctx) => {
		if (ctx.mode !== "tui" && ctx.mode !== "rpc") return;
		const socketPath = process.env.HERDR_SOCKET_PATH;
		const token = generation;
		const refresh = refreshMetadata(event, ctx);
		const currentRevision = revision;
		await refresh;
		if (!metadataFile || !socketPath || token !== generation || currentRevision !== revision) return;
		try { await invokeWithRetry(() => invokeOverviewNameRefresh(socketPath)); }
		catch { warn("Pi name metadata refreshed, but Herdr's passive name refresh failed"); }
	});
	pi.on("session_tree", refreshMetadata);
	pi.on("input", refreshMetadata);
	pi.on("agent_settled", refreshMetadata);
  async function consume(sessionId: string, generation: number, recordId?: string) {
    let wake = false;
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
      wake = true;
    }
    // One wake-up per pass: reconcile reads every record, so per-record calls only add load.
    const socket = process.env.HERDR_SOCKET_PATH?.trim();
    if (!wake || !socket || active !== sessionId || epoch !== generation) return;
    try { await invokeWithRetry(() => invokeOverviewReconcile(socket)); }
    catch { warn("saved recap annotation retained; overview wake-up failed"); }
  }

  pi.on("session_start", (_event, ctx) => {
    if (ctx.mode !== "tui" && ctx.mode !== "rpc") return;
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
  pi.on("session_shutdown", (_event, ctx) => {
    if (ctx.mode !== "tui" && ctx.mode !== "rpc") return;
    active = undefined; epoch++;
  });
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
    // Final settlement is public, but modern Pi counts its awaited hooks as busy.
    // isIdle() is therefore false inside this event; queued input must still wait.
    if ((ctx.mode !== "tui" && ctx.mode !== "rpc") || ctx.hasPendingMessages()) return;
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
