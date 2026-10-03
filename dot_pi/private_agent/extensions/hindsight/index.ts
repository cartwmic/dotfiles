/**
 * hindsight — pi extension: automatic long-term memory via a self-hosted
 * Hindsight server (https://hindsight.vectorize.io).
 *
 * This is the *reliable* path Hindsight recommends — hooks, not the model
 * remembering to call MCP tools. Two behaviors:
 *
 *   - Auto-recall: on `before_agent_start` (once per user prompt), recall
 *     relevant memories and inject them as a hidden `role:"custom"` message
 *     (model sees it, the chat transcript does not) — the additionalContext
 *     equivalent.
 *   - Auto-retain: on `agent_end` (per response cycle), buffer that run's
 *     messages and append them to the session's Hindsight document every N
 *     cycles (fire-and-forget), plus a final awaited flush on
 *     `session_shutdown`. Subagent children (PI_SUBAGENT_CHILD=1) and headless
 *     print/JSON runs (no UI, e.g. Loop Engine workers) skip both.
 *
 * The `hindsight` MCP server (registered separately) still gives the model
 * explicit recall/reflect/retain tools; this extension makes the common case
 * automatic. Mirrors the official Claude Code plugin's hook design.
 *
 * Resilience: every network path is wrapped — a memory failure never blocks
 * or crashes a turn. Toggle live with `/hindsight [on|off|toggle|status]`.
 */
import { randomUUID } from "node:crypto";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { type MemoryItemInput, recall, retain } from "./client.ts";
import { type HindsightConfig, loadConfig, loadEnabled, saveEnabled } from "./config.ts";
import {
	buildRecallQuery,
	deriveProjectTag,
	formatMemoryBlock,
	lastAssistantText,
	type LooseMessage,
	messagesToTranscript,
} from "./content.ts";

function extensionDir(): string {
	return path.dirname(fileURLToPath(import.meta.url));
}

function debugLog(cfg: HindsightConfig, msg: string): void {
	if (cfg.debug) process.stderr.write(`[Hindsight] ${msg}\n`);
}

export type ToggleAction = "on" | "off" | "toggle" | "status" | "invalid";

export function parseToggle(args: string | undefined): ToggleAction {
	const a = (args ?? "").trim().toLowerCase();
	if (a === "" || a === "status") return "status";
	if (a === "on" || a === "off" || a === "toggle") return a;
	return "invalid";
}

export default function (pi: ExtensionAPI): void {
	const dir = extensionDir();
	const cfg = loadConfig(dir);
	let enabled = loadEnabled(dir, cfg.enabled);

	// Source of the most recent input; consumed by the next recall.
	let lastInputSource: string | undefined;

	pi.registerCommand("hindsight", {
		description: "Toggle Hindsight auto memory (on | off | toggle | status)",
		getArgumentCompletions: (prefix: string) =>
			["on", "off", "toggle", "status"]
				.filter((v) => v.startsWith(prefix.toLowerCase()))
				.map((v) => ({ value: v, label: v })),
		handler: async (args: string, ctx) => {
			const action = parseToggle(args);
			if (action === "invalid") {
				ctx.ui.notify("Usage: /hindsight [on | off | toggle | status]", "warning");
				return;
			}
			if (action === "on") enabled = true;
			else if (action === "off") enabled = false;
			else if (action === "toggle") enabled = !enabled;
			if (action !== "status") {
				try {
					saveEnabled(dir, enabled);
				} catch {
					/* in-memory toggle still applies this session */
				}
			}
			const detail = ` (recall:${cfg.autoRecall ? "on" : "off"} retain:${cfg.autoRetain ? "on" : "off"}, bank:${cfg.bankId})`;
			ctx.ui.notify(`Hindsight memory ${enabled ? "ON" : "OFF"}${detail}`, "info");
		},
	});

	// --- Auto-recall: inject relevant memories before the agent loop ---
	pi.on("input", (event) => {
		lastInputSource = event.source;
	});

	pi.on("before_agent_start", async (event, ctx) => {
		const source = lastInputSource;
		lastInputSource = undefined;
		// Only interactive sessions (TUI/RPC): headless print/JSON runs are
		// automation such as Loop Engine workers.
		if (!enabled || !cfg.autoRecall || !ctx.hasUI) return;
		try {
			const query = buildRecallQuery(event.prompt, cfg.recallMaxQueryChars, {
				previousReply: lastAssistantText(ctx.sessionManager.getBranch() as never),
				includePrompt: source !== "extension",
			});
			if (!query) return;
			const results = await recall(cfg, query);
			const block = formatMemoryBlock(results);
			if (!block) {
				debugLog(cfg, `recall: 0 usable memories for "${query.slice(0, 60)}"`);
				return;
			}
			debugLog(cfg, `recall: injected ${results.length} memories`);
			return { message: { customType: "hindsight_memories", content: block, display: false } };
		} catch (err) {
			const msg = err instanceof Error ? err.message : String(err);
			debugLog(cfg, `recall failed: ${msg}`);
			if (cfg.notifyOnRecallFailure && ctx.hasUI) {
				const timedOut = /timed out/i.test(msg);
				ctx.ui.notify(
					timedOut
						? `Hindsight recall timed out (>${cfg.requestTimeoutMs}ms) — no memories injected`
						: `Hindsight recall failed (${msg}) — no memories injected`,
					"warning",
				);
			}
			return;
		}
	});

	// --- Auto-retain: append new conversation to the session document ---
	// agent_end carries only the messages of that one run, so runs are
	// buffered per session and appended. (Shipping them with "replace" used to
	// delete everything the session had retained before.) Append also creates
	// the document if it is missing.
	type Batch = { sessionId: string; cwd: string; messages: LooseMessage[]; operationId: string; failures: number };
	// A batch the server keeps rejecting as invalid (4xx other than 408/429) is
	// dropped rather than blocking the queue. Outages, timeouts, 408/429 and 5xx
	// are kept for later retry.
	const MAX_RETAIN_ATTEMPTS = 3;
	const rejected = (err: unknown) => {
		const status = Number(/^HTTP (\d{3})/.exec(err instanceof Error ? err.message : "")?.[1]);
		return status >= 400 && status < 500 && status !== 408 && status !== 429;
	};
	let open: { sessionId: string; cwd: string; messages: LooseMessage[]; cycles: number } | null = null;
	// Sealed batches not yet acknowledged, oldest first. Each keeps its
	// operation_id across retries so a lost acknowledgement never duplicates it.
	const unsent: Batch[] = [];
	let sending: Promise<void> = Promise.resolve();

	function buildRetain(b: Batch): MemoryItemInput[] | null {
		const transcript = messagesToTranscript(b.messages, {
			roles: cfg.retainRoles,
			includeToolCalls: cfg.retainToolCalls,
		});
		if (!transcript) return null;
		const projectTag = deriveProjectTag(b.cwd);
		// session: stays as provenance; shared scope keeps it from fencing
		// observations into one scope per session (no cross-session dedup).
		const tags = [`session:${b.sessionId}`, ...(projectTag ? [projectTag] : [])];
		return [
			{
				content: transcript,
				tags,
				context: "pi",
				document_id: `pi-session-${b.sessionId}`,
				update_mode: "append",
				observation_scopes: "shared",
			},
		];
	}

	/** Send unsent batches in order; stop at the first failure and keep the rest. */
	async function sendUnsent(): Promise<void> {
		while (unsent.length > 0) {
			const b = unsent[0];
			const items = buildRetain(b);
			if (items) {
				try {
					await retain(cfg, items, b.operationId);
				} catch (err) {
					logRetainError(err);
					if (!rejected(err) || ++b.failures < MAX_RETAIN_ATTEMPTS) return;
					debugLog(cfg, `retain: dropped a batch after ${b.failures} failed attempts`);
				}
			}
			unsent.shift();
		}
	}

	/** Seal the open buffer and queue sending; one send runs at a time. */
	function flush(): Promise<void> {
		if (open && open.messages.length > 0) {
			unsent.push({ sessionId: open.sessionId, cwd: open.cwd, messages: open.messages, operationId: randomUUID(), failures: 0 });
			open = { ...open, messages: [], cycles: 0 };
		}
		sending = sending.then(sendUnsent);
		return sending;
	}

	const logRetainError = (err: unknown) =>
		debugLog(cfg, `retain failed: ${err instanceof Error ? err.message : String(err)}`);

	pi.on("agent_end", async (event, ctx) => {
		if (!enabled || !cfg.autoRetain || !ctx.hasUI) return;
		const sm = ctx.sessionManager;
		const sessionId = sm.getSessionId();
		// Session switched in this process: seal and ship the old session's buffer.
		if (open && open.sessionId !== sessionId) void flush();
		if (!open || open.sessionId !== sessionId) open = { sessionId, cwd: sm.getCwd(), messages: [], cycles: 0 };
		open.messages.push(...((event.messages ?? []) as LooseMessage[]));
		open.cycles++;
		// Fire-and-forget so the turn never blocks on memory writes.
		if (open.cycles >= cfg.retainEveryNTurns) void flush();
	});

	// --- Final flush on shutdown: waits for any in-flight send, then the rest ---
	pi.on("session_shutdown", async () => {
		if (!enabled || !cfg.autoRetain || !cfg.retainOnSessionEnd) return;
		await flush();
	});
}
