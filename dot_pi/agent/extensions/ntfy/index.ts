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
 *   - Can be toggled on/off at runtime with the `/ntfy` command, or by default
 *     via the `enabled` field in config.json. The runtime toggle is persisted
 *     to a sidecar `state.json` (NOT chezmoi-managed) that overrides the config
 *     default, so live toggling never drifts the chezmoi source.
 *   - Delivery is fire-and-forget with a 5s timeout; failures never block or
 *     crash the turn.
 */
import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

const DEFAULT_MAX_EXCERPT = 200;
const STATE_FILE = "state.json";

export interface NtfyConfig {
	url: string;
	maxExcerptChars: number;
	/** Default on/off, from config.json. Overridden at runtime by state.json. */
	enabled: boolean;
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
		// enabled defaults to true unless explicitly set to false.
		const enabled = parsed.enabled !== false;
		return { url, maxExcerptChars, enabled };
	} catch {
		return { url: "", maxExcerptChars: DEFAULT_MAX_EXCERPT, enabled: true };
	}
}

/**
 * Effective enabled state: the runtime override in state.json (if present and
 * valid) wins over the config.json default. Returns `configDefault` when no
 * valid override exists.
 */
export function loadEnabled(dir: string, configDefault: boolean): boolean {
	try {
		const raw = fs.readFileSync(path.join(dir, STATE_FILE), "utf8");
		const parsed = JSON.parse(raw) as { enabled?: unknown };
		if (typeof parsed.enabled === "boolean") return parsed.enabled;
	} catch {
		/* no override */
	}
	return configDefault;
}

/** Persist the runtime on/off override to the sidecar state.json. */
export function saveEnabled(dir: string, value: boolean): void {
	fs.writeFileSync(path.join(dir, STATE_FILE), `${JSON.stringify({ enabled: value }, null, 2)}\n`);
}

export type ToggleAction = "on" | "off" | "toggle" | "status" | "invalid";

/** Parse `/ntfy <args>` into an action. */
export function parseToggle(args: string): ToggleAction {
	const a = (args ?? "").trim().toLowerCase();
	if (a === "" || a === "status") return "status";
	if (a === "on" || a === "enable" || a === "true") return "on";
	if (a === "off" || a === "disable" || a === "false") return "off";
	if (a === "toggle") return "toggle";
	return "invalid";
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

/**
 * Parse `zellij action dump-layout` output for the tab name whose pane has the
 * given cwd. dump-layout stores cwd without a leading slash. Returns the first
 * matching tab's name, or undefined when not found.
 */
export function parseZellijTabName(layout: string, cwd: string): string | undefined {
	const target = cwd.replace(/^\/+/, "");
	let currentTab: string | undefined;
	for (const line of layout.split("\n")) {
		const tabMatch = line.match(/^\s*tab\b[^\n]*\bname="([^"]*)"/);
		if (tabMatch) currentTab = tabMatch[1];
		if (line.includes(`cwd="${target}"`)) return currentTab;
	}
	return undefined;
}

/**
 * Best-effort current zellij tab name for `cwd`. Undefined when not running
 * under zellij or the lookup fails (caller falls back to cwd). cwd-matched, so
 * it identifies THIS session's tab regardless of which tab is focused.
 */
export function resolveZellijTabName(cwd: string): string | undefined {
	if (!process.env.ZELLIJ) return undefined;
	try {
		const out = execFileSync("zellij", ["action", "dump-layout"], {
			encoding: "utf8",
			timeout: 1500,
		});
		return parseZellijTabName(out, cwd);
	} catch {
		return undefined;
	}
}

/**
 * Build the ntfy title + body.
 * Title: `<zellij session> · <zellij tab> · <pi session name>` (each segment
 * omitted when unavailable; the pi session name always present, falling back to
 * a short session id). Body: the excerpt only.
 */
export function buildNotification(opts: {
	sessionName?: string;
	sessionId: string;
	zellijSession?: string;
	tabName?: string;
	excerpt: string;
}): { title: string; body: string } {
	const piName =
		opts.sessionName && opts.sessionName.trim()
			? opts.sessionName.trim()
			: opts.sessionId.slice(0, 8);
	const titleParts = [opts.zellijSession?.trim(), opts.tabName?.trim(), piName].filter(
		(p): p is string => !!p && p.length > 0,
	);
	return { title: titleParts.join(" · "), body: opts.excerpt };
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
	const dir = extensionDir();
	const config = loadConfig(dir);
	// Effective on/off: runtime override (state.json) wins over config default.
	let enabled = loadEnabled(dir, config.enabled);

	pi.registerCommand("ntfy", {
		description: "Toggle ntfy notifications on/off (on | off | toggle | status)",
		getArgumentCompletions: (prefix) =>
			["on", "off", "toggle", "status"]
				.filter((v) => v.startsWith(prefix.toLowerCase()))
				.map((v) => ({ value: v, label: v })),
		handler: async (args, ctx) => {
			const action = parseToggle(args);
			if (action === "invalid") {
				ctx.ui.notify("Usage: /ntfy [on | off | toggle | status]", "warning");
				return;
			}
			if (action === "on") enabled = true;
			else if (action === "off") enabled = false;
			else if (action === "toggle") enabled = !enabled;
			if (action !== "status") {
				try {
					saveEnabled(dir, enabled);
				} catch {
					/* non-fatal: in-memory toggle still applies for this session */
				}
			}
			const detail = config.url ? "" : " (no url configured — still inactive)";
			ctx.ui.notify(`ntfy notifications ${enabled ? "ON" : "OFF"}${detail}`, "info");
		},
	});

	pi.on("agent_end", async (event, ctx) => {
		// hasUI is true in TUI and RPC modes, false in print (-p) / json modes.
		if (!ctx.hasUI) return;
		if (!enabled) return;
		if (!config.url) return;

		const sm = ctx.sessionManager;
		const excerpt = extractExcerpt(lastAssistantText(event.messages ?? []), config.maxExcerptChars);
		const { title, body } = buildNotification({
			sessionName: sm.getSessionName(),
			sessionId: sm.getSessionId(),
			zellijSession: process.env.ZELLIJ_SESSION_NAME,
			tabName: resolveZellijTabName(sm.getCwd()),
			excerpt,
		});

		void sendNotification(config.url, title, body).catch(() => {});
	});
}
