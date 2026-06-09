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
 *   - Auto-retain: on `agent_end` (per response cycle), ship a full-session
 *     transcript to Hindsight every N cycles (fire-and-forget), plus a final
 *     awaited retain on `session_shutdown`.
 *
 * The `hindsight` MCP server (registered separately) still gives the model
 * explicit recall/reflect/retain tools; this extension makes the common case
 * automatic. Mirrors the official Claude Code plugin's hook design.
 *
 * Resilience: every network path is wrapped — a memory failure never blocks
 * or crashes a turn. Toggle live with `/hindsight [on|off|toggle|status]`.
 */
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { recall, retain } from "./client.ts";
import { type HindsightConfig, loadConfig, loadEnabled, saveEnabled } from "./config.ts";
import {
	buildRecallQuery,
	deriveProjectTag,
	formatMemoryBlock,
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

	// Response cycles since the last retain (drives the every-N cadence).
	let cyclesSinceRetain = 0;
	let everRetained = false;
	// Latest conversation snapshot (session_shutdown carries no messages).
	let lastMessages: LooseMessage[] = [];

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
	pi.on("before_agent_start", async (event, ctx) => {
		if (!enabled || !cfg.autoRecall) return;
		try {
			const query = buildRecallQuery(event.prompt, cfg.recallMaxQueryChars);
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
			debugLog(cfg, `recall failed: ${err instanceof Error ? err.message : String(err)}`);
			return;
		}
	});

	// --- Auto-retain: ship a full-session transcript on a cadence ---
	function buildRetain(messages: LooseMessage[], ctx: { cwd: string; sessionId: string }) {
		const transcript = messagesToTranscript(messages, {
			roles: cfg.retainRoles,
			includeToolCalls: cfg.retainToolCalls,
		});
		if (!transcript) return null;
		const projectTag = deriveProjectTag(ctx.cwd);
		const tags = [`session:${ctx.sessionId}`, ...(projectTag ? [projectTag] : [])];
		return {
			items: [
				{
					content: transcript,
					tags,
					context: "pi",
					document_id: `pi-session-${ctx.sessionId}`,
					update_mode: "replace" as const,
				},
			],
			documentTags: projectTag ? [projectTag] : undefined,
		};
	}

	async function doRetain(messages: LooseMessage[], ctx: { cwd: string; sessionId: string }) {
		const built = buildRetain(messages, ctx);
		if (!built) return;
		await retain(cfg, built.items, built.documentTags);
		everRetained = true;
		debugLog(cfg, `retain: shipped full-session (${built.items[0].content.length} chars)`);
	}

	pi.on("agent_end", async (event, ctx) => {
		if (!enabled || !cfg.autoRetain) return;
		lastMessages = (event.messages ?? []) as LooseMessage[];
		cyclesSinceRetain++;
		if (cyclesSinceRetain < cfg.retainEveryNTurns) return;
		cyclesSinceRetain = 0;
		const sm = ctx.sessionManager;
		// Fire-and-forget so the turn never blocks on memory writes.
		void doRetain((event.messages ?? []) as LooseMessage[], {
			cwd: sm.getCwd(),
			sessionId: sm.getSessionId(),
		}).catch((err) =>
			debugLog(cfg, `retain failed: ${err instanceof Error ? err.message : String(err)}`),
		);
	});

	// --- Final flush on shutdown (awaited so it completes before exit) ---
	pi.on("session_shutdown", async (event, ctx) => {
		if (!enabled || !cfg.autoRetain || !cfg.retainOnSessionEnd) return;
		// Skip if nothing happened since the last cadence retain.
		if (cyclesSinceRetain === 0 && everRetained) return;
		const sm = ctx.sessionManager;
		try {
			await doRetain(lastMessages, { cwd: sm.getCwd(), sessionId: sm.getSessionId() });
		} catch (err) {
			debugLog(cfg, `final retain failed: ${err instanceof Error ? err.message : String(err)}`);
		}
	});
}
