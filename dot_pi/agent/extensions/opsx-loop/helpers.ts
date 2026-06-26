// Pure, dependency-free helpers for the opsx-loop kickoff extension.
// Kept free of pi-runtime imports so they are unit-testable via `bun test`.
// The loop mechanism mirrors the validated goal-loop pattern (ADR-0001/0004)
// but this extension is independent — the goal extension is never modified.

export interface LoopVerdict {
	met: boolean;
	reason: string;
}

export interface ResolvedModel {
	value: string | string[] | boolean | null;
	source: string; // env | change | project | user | default | unset
}

/** Parse one `opsx models <role> --json` stdout line; null on malformed input. */
export function parseModelsJson(stdout: string): ResolvedModel | null {
	try {
		const o = JSON.parse((stdout ?? "").trim());
		if (o && typeof o === "object" && "value" in o && "source" in o) {
			return o as ResolvedModel;
		}
	} catch {
		/* ignore malformed resolver output */
	}
	return null;
}

/**
 * Build the OPSX_* env map the extension exports into worker turns, from the
 * parsed `opsx models <role> --json` outputs. Roles export ONLY when CONFIGURED
 * (source not unset/default) so unset roles fall back to the session model.
 * `review` is newline-joined (the resolver/skills accept newline- or
 * comma-delimited). author-in-session always exports its resolved boolean.
 * Values are already provider-qualified by opsx models and pass through.
 * (opsx-loop-kickoff.loop-exports-resolved-role-models)
 */
export function buildModelEnv(resolved: {
	author?: ResolvedModel | null;
	review?: ResolvedModel | null;
	impl?: ResolvedModel | null;
	authorInSession?: ResolvedModel | null;
}): Record<string, string> {
	const env: Record<string, string> = {};
	const configured = (r?: ResolvedModel | null): r is ResolvedModel =>
		r != null && r.source !== "unset" && r.source !== "default" && r.value != null;
	if (configured(resolved.author) && typeof resolved.author.value === "string") {
		env.OPSX_AUTHOR_MODEL = resolved.author.value;
	}
	if (configured(resolved.impl) && typeof resolved.impl.value === "string") {
		env.OPSX_IMPL_MODEL = resolved.impl.value;
	}
	if (configured(resolved.review)) {
		const v = resolved.review.value;
		const list = Array.isArray(v) ? v : typeof v === "string" ? [v] : [];
		if (list.length > 0) env.OPSX_REVIEW_MODELS = list.join("\n");
	}
	if (resolved.authorInSession && typeof resolved.authorInSession.value === "boolean") {
		env.OPSX_AUTHOR_IN_SESSION = resolved.authorInSession.value ? "true" : "false";
	}
	return env;
}

export const LOOP_SUBCOMMANDS: ReadonlyArray<{ value: string; label: string; description: string }> = [
	{ value: "status", label: "status", description: "Show the active loop's change, turns, and budget" },
	{ value: "clear", label: "clear", description: "Stop and clear the active loop (aliases: stop, off, reset, none, cancel)" },
	{ value: "models", label: "models", description: "Read/write role models: models set|get <role> [..] | models list" },
];

const CLEAR_ALIASES = new Set(["clear", "stop", "off", "reset", "none", "cancel"]);
const STATUS_KEYWORDS = new Set(["status", "?"]);

export type LoopArg =
	| { mode: "status" }
	| { mode: "clear" }
	| { mode: "models"; args: string[] }
	| { mode: "set"; change: string; ignored?: string };

/**
 * Classify the `/opsx-loop` argument. Leading keywords (status/clear/models)
 * route to their subcommand with the REMAINING tokens intact; otherwise the
 * first token is the change name and any trailing tokens are surfaced as
 * `ignored` (never silently truncated).
 * (opsx-loop-kickoff.argument-parsing-preserves-full-input,
 *  opsx-loop-kickoff.status-and-clear-subcommands, opsx-loop-kickoff.model-config-subcommand)
 */
export function parseLoopArg(raw: string): LoopArg {
	const arg = (raw ?? "").trim();
	if (arg.length === 0) return { mode: "status" };
	const tokens = arg.split(/\s+/);
	const lower = tokens[0].toLowerCase();
	if (tokens.length === 1 && STATUS_KEYWORDS.has(lower)) return { mode: "status" };
	if (tokens.length === 1 && CLEAR_ALIASES.has(lower)) return { mode: "clear" };
	if (lower === "models") return { mode: "models", args: tokens.slice(1) };
	const change = tokens[0];
	const rest = tokens.slice(1).join(" ");
	return rest.length > 0 ? { mode: "set", change, ignored: rest } : { mode: "set", change };
}

/**
 * Normalize an opsx gate report into a stable stall key: the SORTED set of
 * `GATE-FAIL <check_id>` identifiers, excluding volatile content (paths, SHAs,
 * timestamps, free-text messages). Used to detect a genuinely repeating failure.
 * (opsx-loop-kickoff.stall-detection-stops-the-loop)
 */
export function gateFailKey(report: string): string {
	const ids: string[] = [];
	for (const line of (report ?? "").split(/\r?\n/)) {
		const m = line.match(/^\s*GATE-FAIL\s+(\S+)/);
		if (m) ids.push(m[1]);
	}
	return Array.from(new Set(ids)).sort().join(",");
}

/**
 * Verdict from an opsx gate run: exit 0 = met, any non-zero (or failure to
 * execute) = not met, with the gate's combined output as the reason.
 * Pure; never throws. (opsx-loop-kickoff.opsx-gate-is-the-deterministic-judge)
 */
export function verdictFromExit(code: number | null, output: string): LoopVerdict {
	const out = (output ?? "").trim();
	if (code === 0) return { met: true, reason: out.slice(0, 2000) || "opsx gate exited 0" };
	return { met: false, reason: out.slice(0, 2000) || `opsx gate exited ${code ?? "non-zero"}` };
}

/**
 * Parse `loop_max_iterations` from a change's review.md YAML front-matter
 * (between the first two '---' fences). Falls back to `def` when absent or
 * unparseable. (opsx-loop-kickoff.budget-from-review-front-matter)
 */
export function parseLoopBudget(reviewMd: string, def = 40): number {
	const text = reviewMd ?? "";
	const lines = text.split(/\r?\n/);
	if (lines[0]?.trim() !== "---") return def;
	for (let i = 1; i < lines.length; i++) {
		if (lines[i].trim() === "---") break;
		const m = lines[i].match(/^\s*loop_max_iterations\s*:\s*(\d+)/);
		if (m) {
			const n = Number.parseInt(m[1], 10);
			if (Number.isFinite(n) && n > 0) return n;
		}
	}
	return def;
}
