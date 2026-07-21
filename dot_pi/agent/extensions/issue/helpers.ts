/**
 * Pure helpers: parse, sanitize, bind state, nudge cadence.
 */

export type IssueVerb =
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

export type ProviderName = "jira" | "github";

export interface ParsedCommand {
	verb: IssueVerb;
	provider: ProviderName | null;
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

const PROVIDERS = new Set<string>(["jira", "github"]);

/** Parse `/issue <verb> [provider] [rest]`. Empty args → status. */
export function parseCommand(args: string | undefined): ParsedCommand {
	const trimmed = (args ?? "").trim();
	if (!trimmed) return { verb: "status", provider: null, rest: "" };

	const parts = trimmed.split(/\s+/);
	const head = parts[0].toLowerCase();
	if (!VERBS.has(head)) {
		return { verb: "invalid", provider: null, rest: trimmed };
	}

	let provider: ProviderName | null = null;
	let restStart = 1;
	if (parts.length > 1 && PROVIDERS.has(parts[1].toLowerCase())) {
		provider = parts[1].toLowerCase() as ProviderName;
		restStart = 2;
	}

	const rest = parts.slice(restStart).join(" ");
	return { verb: head as IssueVerb, provider, rest };
}

/** Strip secrets from error messages. */
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

/** Per-provider bind state. */
export interface ProviderBindState {
	boundKey: string | null;
	lastSyncAt: number | null;
	pendingContextInject: boolean;
	pendingPayload?: string;
}

/** Session state with multi-provider support. */
export interface SessionState {
	enabled: boolean;
	nudgeEveryNTurns: number;
	agentEndCount: number;
	providers: Map<string, ProviderBindState>;
}

export function createSessionState(
	enabled = true,
	nudgeEveryNTurns = 5,
): SessionState {
	return {
		enabled,
		nudgeEveryNTurns,
		agentEndCount: 0,
		providers: new Map(),
	};
}

export function getProviderState(state: SessionState, provider: string): ProviderBindState {
	if (!state.providers.has(provider)) {
		state.providers.set(provider, {
			boundKey: null,
			lastSyncAt: null,
			pendingContextInject: false,
		});
	}
	return state.providers.get(provider)!;
}

export function bindKey(state: ProviderBindState, key: string): void {
	state.boundKey = key.trim();
	state.pendingContextInject = false;
	state.pendingPayload = undefined;
}

export function clearBind(state: ProviderBindState): void {
	state.boundKey = null;
	state.lastSyncAt = null;
	state.pendingContextInject = false;
	state.pendingPayload = undefined;
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
	providerStates: Array<{ name: string; boundKey: string | null; lastSyncAt: number | null }>;
	nudgeEveryNTurns: number;
	now?: number;
}): string {
	const now = opts.now ?? Date.now();
	const parts = [`Issue helper ${opts.enabled ? "ON" : "OFF"}`];
	for (const ps of opts.providerStates) {
		const bind = ps.boundKey ?? "unbound";
		let sync = "never";
		if (ps.lastSyncAt != null) {
			const mins = Math.max(0, Math.floor((now - ps.lastSyncAt) / 60_000));
			sync = mins === 0 ? "just now" : `${mins}m ago`;
		}
		parts.push(`${ps.name}: ${bind} (${sync})`);
	}
	parts.push(`nudgeEveryNTurns: ${opts.nudgeEveryNTurns}`);
	return parts.join(" | ");
}

export function formatNudgeMessage(state: SessionState, providerNames: string[]): string {
	const lines: string[] = [];
	for (const name of providerNames) {
		const ps = getProviderState(state, name);
		if (ps.boundKey) {
			const age =
				ps.lastSyncAt == null
					? "never synced"
					: `last sync ${Math.max(0, Math.floor((Date.now() - ps.lastSyncAt) / 60_000))}m ago`;
			lines.push(`${name} ${ps.boundKey} (${age})`);
		} else {
			lines.push(`${name} unbound`);
		}
	}
	return `Issues: ${lines.join(", ")} — /issue sync | /issue context`;
}

/** Detect issue key format: Jira (PROJ-123) vs GitHub (123 or owner/repo#123). */
export function detectProviderFromKey(key: string): ProviderName | null {
	const trimmed = key.trim();
	if (/^[A-Z][A-Z0-9]+-\d+$/i.test(trimmed)) return "jira";
	if (/^\d+$/.test(trimmed) || /^[^/]+\/[^#]+#\d+$/.test(trimmed)) return "github";
	return null;
}
