/**
 * ntfy notify — pi extension
 *
 * On every `agent_end` (the agent returning to awaiting-input), pushes an
 * ntfy notification so a remote user (phone -> Termux -> SSH -> zellij -> pi)
 * knows which pi session is waiting and what it last said.
 *
 * Prerequisites:
 *   - ntfy server reachable at the URL in config.json
 *     (default: https://ntfy.internal.cartwmic.com/pi — internal-only host,
 *      not a secret, committed as a plain config value).
 *   - ntfy Android app installed and subscribed to the topic (`pi`).
 *
 * Behavior:
 *   - Skips non-interactive sessions (print/json mode) via `ctx.hasUI`.
 *   - No-ops silently when `url` is empty/missing.
 *   - Delivery is fire-and-forget with a 5s timeout; failures never block or
 *     crash the turn.
 */
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

const DEFAULT_MAX_EXCERPT = 200;

export interface NtfyConfig {
	url: string;
	maxExcerptChars: number;
}

/** Read config.json beside this module. Missing/unreadable -> disabled config. */
export function loadConfig(dir: string): NtfyConfig {
	try {
		const raw = fs.readFileSync(path.join(dir, "config.json"), "utf8");
		const parsed = JSON.parse(raw) as Partial<NtfyConfig>;
		const url = typeof parsed.url === "string" ? parsed.url.trim() : "";
		const maxExcerptChars =
			typeof parsed.maxExcerptChars === "number" && parsed.maxExcerptChars > 0
				? Math.floor(parsed.maxExcerptChars)
				: DEFAULT_MAX_EXCERPT;
		return { url, maxExcerptChars };
	} catch {
		return { url: "", maxExcerptChars: DEFAULT_MAX_EXCERPT };
	}
}

/** Extract the last assistant message's response text (thinking excluded). */
export function lastAssistantText(messages: readonly unknown[]): string {
	for (let i = messages.length - 1; i >= 0; i--) {
		const m = messages[i] as { role?: string; content?: unknown } | null;
		if (m && m.role === "assistant" && Array.isArray(m.content)) {
			const parts: string[] = [];
			for (const block of m.content as Array<{ type?: string; text?: string }>) {
				if (block && block.type === "text" && typeof block.text === "string") {
					parts.push(block.text);
				}
			}
			return parts.join("\n");
		}
	}
	return "";
}

/** Collapse whitespace and truncate to maxChars with a `…` indicator. */
export function extractExcerpt(text: string, maxChars: number): string {
	const collapsed = (text ?? "").replace(/\s+/g, " ").trim();
	if (!collapsed) return "(no text)";
	if (collapsed.length <= maxChars) return collapsed;
	return `${collapsed.slice(0, Math.max(0, maxChars - 1)).trimEnd()}…`;
}

/** Build the ntfy title + body. Omits the zellij segment when unset. */
export function buildNotification(opts: {
	sessionName?: string;
	sessionId: string;
	zellij?: string;
	cwd: string;
	excerpt: string;
}): { title: string; body: string } {
	const name =
		opts.sessionName && opts.sessionName.trim()
			? opts.sessionName.trim()
			: opts.sessionId.slice(0, 8);
	const segments: string[] = [];
	if (opts.zellij && opts.zellij.trim()) segments.push(`zellij:${opts.zellij.trim()}`);
	segments.push(opts.cwd);
	segments.push(opts.excerpt);
	return { title: `pi ready: ${name}`, body: segments.join(" · ") };
}

/** POST a notification to ntfy. Fire-and-forget; caller swallows errors. */
export async function sendNotification(url: string, title: string, body: string): Promise<void> {
	await fetch(url, {
		method: "POST",
		headers: { Title: title, Priority: "high", Tags: "robot" },
		body,
		signal: AbortSignal.timeout(5000),
	});
}

function extensionDir(): string {
	return path.dirname(fileURLToPath(import.meta.url));
}

export default function (pi: ExtensionAPI): void {
	const config = loadConfig(extensionDir());

	pi.on("agent_end", async (event, ctx) => {
		// hasUI is true in TUI and RPC modes, false in print (-p) / json modes.
		if (!ctx.hasUI) return;
		if (!config.url) return;

		const sm = ctx.sessionManager;
		const excerpt = extractExcerpt(lastAssistantText(event.messages ?? []), config.maxExcerptChars);
		const { title, body } = buildNotification({
			sessionName: sm.getSessionName(),
			sessionId: sm.getSessionId(),
			zellij: process.env.ZELLIJ_SESSION_NAME,
			cwd: sm.getCwd(),
			excerpt,
		});

		void sendNotification(config.url, title, body).catch(() => {});
	});
}
