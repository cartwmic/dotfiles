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
 *     crash the turn, but every failure IS surfaced: a TUI warning per failed
 *     send, `/ntfy status` outcome counters, and a capped send.log beside this
 *     module (metadata only — never bodies or credentials). Non-2xx responses
 *     count as failures.
 */
import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

const DEFAULT_MAX_EXCERPT = 200;
const DEFAULT_JUMP_DEEPLINK_BASE = "termux://zellij-jump";
const STATE_FILE = "state.json";

export interface NtfyConfig {
	url: string;
	maxExcerptChars: number;
	/** Default on/off, from config.json. Overridden at runtime by state.json. */
	enabled: boolean;
	/**
	 * Deep-link scheme+host the termux-app fork registers for the notification
	 * tap-to-jump. The pane id rides the URL PATH (`<base>/<pane-id>`), which is
	 * what the fork's ZellijJumpHandler parses. Default: termux://zellij-jump.
	 */
	jumpDeepLinkBase: string;
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
		const jumpDeepLinkBase =
			typeof parsed.jumpDeepLinkBase === "string" && parsed.jumpDeepLinkBase.trim()
				? parsed.jumpDeepLinkBase.trim()
				: DEFAULT_JUMP_DEEPLINK_BASE;
		return { url, maxExcerptChars, enabled, jumpDeepLinkBase };
	} catch {
		return {
			url: "",
			maxExcerptChars: DEFAULT_MAX_EXCERPT,
			enabled: true,
			jumpDeepLinkBase: DEFAULT_JUMP_DEEPLINK_BASE,
		};
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
 * Build a notification excerpt from `ask_user_question` tool args. Uses the
 * first question's text, prefixed with a `[N questions]` count when the call
 * batches several. The leading `❓` rides in the UTF-8 request body (not the
 * header), so the emoji renders fine.
 */
export function extractQuestionExcerpt(args: unknown, maxChars: number): string {
	const questions =
		args && typeof args === "object" && Array.isArray((args as { questions?: unknown }).questions)
			? (args as { questions: Array<{ question?: unknown }> }).questions
			: [];
	if (questions.length === 0) return extractExcerpt("❓ (waiting for your answer)", maxChars);
	const first = questions[0];
	const text = first && typeof first.question === "string" ? first.question : "(question)";
	const prefix = questions.length > 1 ? `[${questions.length} questions] ` : "";
	return extractExcerpt(`❓ ${prefix}${text}`, maxChars);
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
 * Title: `<zellij session> / <zellij tab> / <pi session name>` (each segment
 * omitted when unavailable; the pi session name always present, falling back to
 * a short session id). The separator is ASCII because the title is sent as an
 * HTTP header (ntfy `Title:`), which is not UTF-8 safe — non-ASCII renders as
 * the replacement char. Body: the excerpt only (sent as the UTF-8 request
 * body, so Unicode there is fine).
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
	return { title: titleParts.join(" / "), body: opts.excerpt };
}

/**
 * Build the ntfy `Click` deep-link that makes tapping the notification jump the
 * remote zellij session to the pi process's OWN pane. Returns undefined when no
 * usable pane id is available (not running under zellij, or a non-terminal pane
 * such as `plugin_N`). The pane id ($ZELLIJ_PANE_ID, form `terminal_N` or bare
 * `N`) rides the URL PATH — the termux-app fork's ZellijJumpHandler parses it
 * there and invokes ~/bin/zellij-jump, which side-channels
 * `ssh remote 'zellij pipe --name jump_pane <pane>'` to harpoon. Slot numbers
 * are intentionally NOT used (reassignable between send and tap); the pane id is
 * stable.
 */
export function buildJumpClickUrl(
	paneId: string | undefined,
	base: string = DEFAULT_JUMP_DEEPLINK_BASE,
): string | undefined {
	const id = (paneId ?? "").trim();
	// Only terminal panes are jumpable; harpoon's parse_pane_id rejects other
	// underscore-tagged kinds (e.g. `plugin_3`) and non-numeric tails.
	if (!/^(terminal_)?\d+$/.test(id)) return undefined;
	return `${base.replace(/\/+$/, "")}/${encodeURIComponent(id)}`;
}

/**
 * POST a notification to ntfy. Rejects on network error/timeout AND on any
 * non-2xx response (pi-ntfy-notify "Non-2xx response is a failure"). Callers
 * dispatch fire-and-forget and route the settled outcome through
 * `reactToSendOutcome` — failures are surfaced, never silently swallowed.
 */
export async function sendNotification(
	url: string,
	title: string,
	body: string,
	tags = "robot",
	clickUrl?: string,
): Promise<void> {
	const headers: Record<string, string> = { Title: title, Priority: "high", Tags: tags };
	// ntfy does NOT propagate custom X-* headers to the client, so the jump target
	// MUST ride the `Click` header (the tap action URL), never a custom header.
	if (clickUrl) headers.Click = clickUrl;
	const res = await fetch(url, {
		method: "POST",
		headers,
		body,
		signal: AbortSignal.timeout(5000),
	});
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

// ── Send-outcome visibility (pi-ntfy-notify failure-visibility surfaces) ─────

const SEND_LOG_FILE = "send.log";
const SEND_LOG_ROTATED_FILE = "send.log.old";
const SEND_LOG_MAX_BYTES = 200 * 1024;

export interface SendState {
	okCount: number;
	failCount: number;
	lastOkAt?: Date;
	lastFailAt?: Date;
	lastFailReason?: string;
}

export function newSendState(): SendState {
	return { okCount: 0, failCount: 0 };
}

/** Bounded, secret-free failure reason from a rejected send. */
export function describeSendError(err: unknown): string {
	const raw = err instanceof Error ? `${err.name}: ${err.message}` : String(err);
	// Metadata only — collapse whitespace, hard-bound length. Never includes
	// headers or body content by construction (Error messages here are either
	// `HTTP <status>` or runtime fetch/abort errors).
	return raw.replace(/\s+/g, " ").trim().slice(0, 200) || "unknown error";
}

/** Update in-memory session state with a settled send outcome. */
export function recordOutcome(state: SendState, ok: boolean, reason?: string, at: Date = new Date()): void {
	if (ok) {
		state.okCount++;
		state.lastOkAt = at;
	} else {
		state.failCount++;
		state.lastFailAt = at;
		state.lastFailReason = reason ?? "unknown error";
	}
}

/** One send-log line: timestamp, outcome, bounded reason. Metadata only. */
export function buildLogLine(ok: boolean, reason?: string, at: Date = new Date()): string {
	return ok ? `${at.toISOString()} ok` : `${at.toISOString()} fail ${reason ?? "unknown error"}`;
}

/**
 * Append a line to the capped send log in `dir`. When the log exceeds the cap
 * it is rotated to `send.log.old` (previous rotation overwritten) so growth is
 * bounded (pi-ntfy-notify "Capped Send Log"). Never throws — logging must not
 * become a new failure mode.
 */
export function appendSendLog(dir: string, line: string, maxBytes: number = SEND_LOG_MAX_BYTES): void {
	try {
		const file = path.join(dir, SEND_LOG_FILE);
		try {
			if (fs.statSync(file).size >= maxBytes) {
				fs.renameSync(file, path.join(dir, SEND_LOG_ROTATED_FILE));
			}
		} catch {
			/* no existing log — nothing to rotate */
		}
		fs.appendFileSync(file, `${line}\n`);
	} catch {
		/* swallow: the log is best-effort; state + warning remain */
	}
}

/** Human-readable status line for `/ntfy status`. */
export function formatSendStatus(state: SendState): string {
	if (state.okCount === 0 && state.failCount === 0) return "no sends this session";
	const parts = [`sends: ${state.okCount} ok / ${state.failCount} failed`];
	if (state.lastOkAt) parts.push(`last ok ${state.lastOkAt.toISOString()}`);
	if (state.lastFailAt) {
		parts.push(`last fail ${state.lastFailAt.toISOString()} (${state.lastFailReason ?? "unknown error"})`);
	}
	return parts.join("; ");
}

/**
 * Route a dispatched send's settled outcome to the visibility surfaces:
 * in-memory state, the capped send log, and (on failure, when a UI exists) a
 * TUI warning for EVERY failure (owner-settled policy). The turn path never
 * awaits this — dispatch stays fire-and-forget.
 */
export function reactToSendOutcome(
	promise: Promise<void>,
	state: SendState,
	dir: string,
	warn: (message: string) => void,
): void {
	promise.then(
		() => {
			recordOutcome(state, true);
			appendSendLog(dir, buildLogLine(true));
		},
		(err: unknown) => {
			const reason = describeSendError(err);
			recordOutcome(state, false, reason);
			appendSendLog(dir, buildLogLine(false, reason));
			try {
				warn(`ntfy send failed: ${reason}`);
			} catch {
				/* warning surface unavailable — state + log already recorded */
			}
		},
	);
}

function extensionDir(): string {
	return path.dirname(fileURLToPath(import.meta.url));
}

export default function (pi: ExtensionAPI): void {
	const dir = extensionDir();
	const config = loadConfig(dir);
	// Effective on/off: runtime override (state.json) wins over config default.
	let enabled = loadEnabled(dir, config.enabled);
	// Per-session send outcomes (pi-ntfy-notify "Status Reports Send Outcomes").
	const sendState = newSendState();

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
			const suffix = action === "status" ? ` — ${formatSendStatus(sendState)}` : "";
			ctx.ui.notify(`ntfy notifications ${enabled ? "ON" : "OFF"}${detail}${suffix}`, "info");
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
		const clickUrl = buildJumpClickUrl(process.env.ZELLIJ_PANE_ID, config.jumpDeepLinkBase);

		// Fire-and-forget on the turn path; outcome routed to the visibility
		// surfaces (state + capped log + every-failure TUI warning).
		reactToSendOutcome(
			sendNotification(config.url, title, body, "robot", clickUrl),
			sendState,
			dir,
			(message) => ctx.ui.notify(message, "warning"),
		);
	});

	// The agent pauses mid-turn while an `ask_user_question` dialog is open, so
	// `agent_end` never fires for it. Notify on the tool's execution start (which
	// runs just before the blocking overlay) so a remote user knows a question is
	// waiting. `tool_execution_start` carries a ctx (hasUI + sessionManager); the
	// raw `rpiv:ask-user:prompt` event channel does not.
	pi.on("tool_execution_start", async (event, ctx) => {
		if (event.toolName !== "ask_user_question") return;
		if (!ctx.hasUI) return;
		if (!enabled) return;
		if (!config.url) return;

		const sm = ctx.sessionManager;
		const excerpt = extractQuestionExcerpt(event.args, config.maxExcerptChars);
		const { title, body } = buildNotification({
			sessionName: sm.getSessionName(),
			sessionId: sm.getSessionId(),
			zellijSession: process.env.ZELLIJ_SESSION_NAME,
			tabName: resolveZellijTabName(sm.getCwd()),
			excerpt,
		});
		const clickUrl = buildJumpClickUrl(process.env.ZELLIJ_PANE_ID, config.jumpDeepLinkBase);

		reactToSendOutcome(
			sendNotification(config.url, title, body, "question", clickUrl),
			sendState,
			dir,
			(message) => ctx.ui.notify(message, "warning"),
		);
	});
}
