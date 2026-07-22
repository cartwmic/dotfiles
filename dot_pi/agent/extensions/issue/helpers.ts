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
	| "config"
	| "invalid";

export type ProviderName = "jira" | "github";

export interface ParsedCommand {
	verb: IssueVerb;
	provider: ProviderName | null;
	/** Remainder normalized on whitespace (single-spaced). */
	rest: string;
	/** Remainder verbatim (internal + trailing whitespace preserved). For verbatim comment bodies. */
	rawRest: string;
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
	"config",
]);

const PROVIDERS = new Set<string>(["jira", "github"]);

/** Parse `/issue <verb> [provider] [rest]`. Empty args → status. */
export function parseCommand(args: string | undefined): ParsedCommand {
	const trimmed = (args ?? "").trim();
	if (!trimmed) return { verb: "status", provider: null, rest: "", rawRest: "" };

	const parts = trimmed.split(/\s+/);
	const head = parts[0].toLowerCase();
	if (!VERBS.has(head)) {
		return { verb: "invalid", provider: null, rest: trimmed, rawRest: trimmed };
	}

	let provider: ProviderName | null = null;
	let restStart = 1;
	if (parts.length > 1 && PROVIDERS.has(parts[1].toLowerCase())) {
		provider = parts[1].toLowerCase() as ProviderName;
		restStart = 2;
	}

	const rest = parts.slice(restStart).join(" ");
	// rawRest: strip the leading verb (and optional provider) token + the single
	// whitespace run after each, preserving all remaining whitespace verbatim.
	let rawRest = trimmed.slice(parts[0].length).replace(/^\s+/, "");
	if (restStart === 2) rawRest = rawRest.slice(parts[1].length).replace(/^\s+/, "");
	return { verb: head as IssueVerb, provider, rest, rawRest };
}

/** Strip secrets from error messages. */
export function sanitizeErrorMessage(err: unknown): string {
	let msg = err instanceof Error ? err.message : String(err ?? "unknown error");
	// A quoted-or-unquoted value: a full single/double quoted string (honoring
	// escaped quotes, so internal commas/spaces stay inside the value) OR an
	// unquoted run up to a delimiter. Reused below so punctuation-bearing and
	// structured secrets are redacted whole rather than partially.
	const VALUE = String.raw`(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|[^\s"',;}\]]+)`;
	// Bearer / Basic schemes — opaque credential.
	msg = msg.replace(new RegExp(String.raw`\b(Bearer|Basic)\s+${VALUE}`, "gi"), "$1 [redacted]");
	// Authorization (header / JSON / equals form): redact the ENTIRE value to the
	// end of the line — auth values can be structured (Digest username="..",
	// response="..") and must not leak any component.
	msg = msg.replace(/(["']?Authorization["']?\s*[:=]\s*)[^\n]*/gi, "$1[redacted]");
	// Known secret-bearing keys — redact the whole (possibly quoted) value.
	msg = msg.replace(
		new RegExp(
			String.raw`(\b(?:access_token|refresh_token|api[-_]?key|client_secret|secret|password|private[-_]token|token)\b["']?\s*[:=]\s*)${VALUE}`,
			"gi",
		),
		"$1[redacted]",
	);
	msg = msg.replace(/\s+/g, " ").trim();
	if (msg.length > 240) msg = `${msg.slice(0, 237)}...`;
	return msg || "unknown error";
}

/** Per-provider bind state. */
export interface ProviderBindState {
	boundKey: string | null;
	/** Wall-clock of last successful sync. Display/nudge only. */
	lastSyncAt: number | null;
	/**
	 * Session-entry id of the last entry covered by the previous checkpoint. This
	 * (not the timestamp) is the precise transcript cursor: the next checkpoint
	 * covers entries AFTER this id. Position-based anchoring avoids equal-ms
	 * double-counting, clock-skew skips, and malformed-timestamp drops.
	 */
	lastSyncEntryId: string | null;
	/**
	 * Monotonic counter bumped on every bind/clear. Captured before an in-flight
	 * async checkpoint and re-checked before posting/advancing so a concurrent
	 * clear→rebind (even to the SAME key) invalidates the stale checkpoint —
	 * value-equality on boundKey alone can't detect that.
	 */
	bindGeneration: number;
	/** True while a sync is in flight for this provider (prevents concurrent double-post). */
	syncing: boolean;
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
			lastSyncEntryId: null,
			bindGeneration: 0,
			syncing: false,
			pendingContextInject: false,
		});
	}
	return state.providers.get(provider)!;
}

export function bindKey(state: ProviderBindState, key: string): void {
	const k = key.trim();
	// Binding a DIFFERENT issue resets the checkpoint anchor: the newly bound
	// issue has never been checkpointed, so its first checkpoint should cover the
	// whole session (lastSyncAt=null) rather than inherit the prior issue's anchor.
	if (state.boundKey !== k) {
		state.lastSyncAt = null;
		state.lastSyncEntryId = null;
	}
	state.boundKey = k;
	state.bindGeneration++;
	state.pendingContextInject = false;
	state.pendingPayload = undefined;
}

export function clearBind(state: ProviderBindState): void {
	state.boundKey = null;
	state.lastSyncAt = null;
	state.lastSyncEntryId = null;
	state.bindGeneration++;
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
