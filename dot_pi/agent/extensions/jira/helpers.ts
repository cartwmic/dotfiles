/**
 * Pure helpers: parse, sanitize, bind state, nudge cadence.
 */

export type JiraVerb =
	| "on"
	| "off"
	| "toggle"
	| "status"
	| "bind"
	| "clear"
	| "show"
	| "search"
	| "create"
	| "sync"
	| "transition"
	| "context"
	| "invalid";

export interface ParsedCommand {
	verb: JiraVerb;
	rest: string;
}

const VERBS = new Set<string>([
	"on",
	"off",
	"toggle",
	"status",
	"bind",
	"clear",
	"show",
	"search",
	"create",
	"sync",
	"transition",
	"context",
]);

/** Parse `/jira <verb> [rest]`. Empty args → status. */
export function parseCommand(args: string | undefined): ParsedCommand {
	const trimmed = (args ?? "").trim();
	if (!trimmed) return { verb: "status", rest: "" };
	const sp = trimmed.search(/\s/);
	const head = (sp === -1 ? trimmed : trimmed.slice(0, sp)).toLowerCase();
	const rest = sp === -1 ? "" : trimmed.slice(sp + 1).trim();
	if (VERBS.has(head)) return { verb: head as JiraVerb, rest };
	return { verb: "invalid", rest: trimmed };
}

/** Strip secrets from error messages (D8). */
export function sanitizeErrorMessage(err: unknown): string {
	let msg = err instanceof Error ? err.message : String(err ?? "unknown error");
	msg = msg.replace(/Bearer\s+[A-Za-z0-9._\-+/=]+/gi, "Bearer [redacted]");
	msg = msg.replace(/access_token["']?\s*[:=]\s*["']?[^"'&\s]+/gi, "access_token=[redacted]");
	msg = msg.replace(/refresh_token["']?\s*[:=]\s*["']?[^"'&\s]+/gi, "refresh_token=[redacted]");
	msg = msg.replace(/Authorization:\s*[^\n]+/gi, "Authorization: [redacted]");
	msg = msg.replace(/\s+/g, " ").trim();
	if (msg.length > 240) msg = `${msg.slice(0, 237)}...`;
	return msg || "unknown error";
}

export interface SessionBindState {
	boundKey: string | null;
	lastSyncAt: number | null;
	pendingContextInject: boolean;
	agentEndCount: number;
}

export function createSessionState(): SessionBindState {
	return {
		boundKey: null,
		lastSyncAt: null,
		pendingContextInject: false,
		agentEndCount: 0,
	};
}

export function bindKey(state: SessionBindState, key: string): void {
	state.boundKey = key.trim().toUpperCase();
}

export function clearBind(state: SessionBindState): void {
	state.boundKey = null;
	state.pendingContextInject = false;
}

/** True when a nudge should fire after this agent_end. */
export function shouldNudge(
	enabled: boolean,
	nudgeEveryNTurns: number,
	agentEndCount: number,
): boolean {
	if (!enabled) return false;
	if (nudgeEveryNTurns <= 0) return false;
	return agentEndCount > 0 && agentEndCount % nudgeEveryNTurns === 0;
}

export function formatStatus(opts: {
	enabled: boolean;
	boundKey: string | null;
	lastSyncAt: number | null;
	nudgeEveryNTurns: number;
	pendingContextInject: boolean;
	now?: number;
}): string {
	const now = opts.now ?? Date.now();
	const bind = opts.boundKey ?? "unbound";
	let sync = "never";
	if (opts.lastSyncAt != null) {
		const mins = Math.max(0, Math.floor((now - opts.lastSyncAt) / 60_000));
		sync = mins === 0 ? "just now" : `${mins}m ago`;
	}
	return [
		`Jira helper ${opts.enabled ? "ON" : "OFF"}`,
		`bound: ${bind}`,
		`last sync: ${sync}`,
		`nudgeEveryNTurns: ${opts.nudgeEveryNTurns}`,
		`pendingContextInject: ${opts.pendingContextInject ? "yes" : "no"}`,
	].join(" | ");
}

export function formatNudgeMessage(state: SessionBindState): string {
	if (!state.boundKey) {
		return "Jira: unbound — /jira search | /jira bind KEY | /jira create";
	}
	const age =
		state.lastSyncAt == null
			? "never synced"
			: `last sync ${Math.max(0, Math.floor((Date.now() - state.lastSyncAt) / 60_000))}m ago`;
	return `Jira: bound ${state.boundKey}, ${age} — /jira sync | /jira context`;
}

/** Heuristic: treat as JQL if it contains JQL operators/keywords. */
export function toSearchJql(textOrJql: string): string {
	const t = textOrJql.trim();
	if (!t) return "assignee = currentUser() ORDER BY updated DESC";
	if (/\b(AND|OR|ORDER BY|project\s*=|assignee\s*=|status\s*=|~)\b/i.test(t)) return t;
	const escaped = t.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
	return `summary ~ "${escaped}" OR description ~ "${escaped}" ORDER BY updated DESC`;
}

export function looksLikeIssueKey(s: string): boolean {
	return /^[A-Z][A-Z0-9]+-\d+$/i.test(s.trim());
}
