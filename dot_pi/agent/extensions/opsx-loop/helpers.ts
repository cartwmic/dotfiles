// Pure, dependency-free helpers for the opsx-loop kickoff extension.
// Kept free of pi-runtime imports so they are unit-testable via `bun test`.
// The loop mechanism mirrors the validated goal-loop pattern (ADR-0001/0004)
// but this extension is independent — the goal extension is never modified.
import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";

/**
 * Deterministic content digest of every file under `dir` (recursive, path-sorted).
 * Captures ANY working-tree content change — committed, staged, unstaged, or
 * untracked — uniformly, so the stall guard's progress signal does not depend on
 * git index state. Returns "" for a missing/unreadable dir.
 * (opsx-loop.stall-detection-stops-the-loop)
 */
export function hashDir(dir: string): string {
	const h = createHash("sha1");
	const walk = (p: string): void => {
		let entries: ReturnType<typeof readdirSync>;
		try {
			entries = readdirSync(p, { withFileTypes: true });
		} catch {
			return;
		}
		for (const e of [...entries].sort((a, b) => (a.name < b.name ? -1 : 1))) {
			const fp = join(p, e.name);
			if (e.isDirectory()) walk(fp);
			else {
				try {
					// relative path keeps the digest location-independent (same change dir
					// across turns hashes only by content + intra-dir layout).
					h.update(`${relative(dir, fp)}\0`);
					h.update(readFileSync(fp));
				} catch {
					/* unreadable file: skip */
				}
			}
		}
	};
	walk(dir);
	return h.digest("hex");
}

export interface LoopVerdict {
	met: boolean;
	reason: string;
}

export interface ResolvedModel {
	value: string | string[] | boolean | null;
	source: string; // env | change | project | user | default | unset
}

/**
 * Every OPSX_* role env var the loop may export. exportModelEnv() clears ALL of
 * these from process.env before applying a change's resolved config, so a
 * previous loop's exports can never leak into a later loop (or into the gate's
 * author-marker resolution, which treats env as the highest-precedence layer).
 * (opsx-loop.loop-exports-resolved-role-models)
 */
export const OPSX_MODEL_ENV_KEYS = [
	"OPSX_AUTHOR_MODEL",
	"OPSX_REVIEW_MODELS",
	"OPSX_IMPL_MODEL",
	"OPSX_AUTHOR_IN_SESSION",
] as const;

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
 * (opsx-loop.loop-exports-resolved-role-models)
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
	{ value: "goal", label: "goal", description: "Start a loop from a goal (goal <text>) or the current conversation (goal, no text)" },
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
	| { mode: "goal"; goal?: string }
	| { mode: "set"; change: string; ignored?: string };

/**
 * Classify the `/opsx-loop` argument. Leading keywords (goal/status/clear/models)
 * route to their subcommand with the REMAINING tokens intact; otherwise the
 * first token is the change name and any trailing tokens are surfaced as
 * `ignored` (never silently truncated).
 *
 * `goal` is the conversation/goal-driven entry: `goal <free text>` preserves the
 * ENTIRE remaining input as the goal (multi-word, never truncated); `goal` with
 * no following text starts from the current conversation contents (goal omitted).
 * (opsx-loop.argument-parsing-preserves-full-input,
 *  opsx-loop.status-and-clear-subcommands, opsx-loop.model-config-subcommand,
 *  opsx-loop.goal-and-conversation-kickoff)
 */
export function parseLoopArg(raw: string): LoopArg {
	const arg = (raw ?? "").trim();
	if (arg.length === 0) return { mode: "status" };
	const tokens = arg.split(/\s+/);
	const lower = tokens[0].toLowerCase();
	// Leading keywords route to their subcommand with remaining tokens; they win
	// over change-name parsing so trailing tokens never reinterpret them as a change.
	if (STATUS_KEYWORDS.has(lower)) return { mode: "status" };
	if (CLEAR_ALIASES.has(lower)) return { mode: "clear" };
	if (lower === "models") return { mode: "models", args: tokens.slice(1) };
	if (lower === "goal") {
		const goal = tokens.slice(1).join(" ").trim();
		return goal.length > 0 ? { mode: "goal", goal } : { mode: "goal" };
	}
	const change = tokens[0];
	const rest = tokens.slice(1).join(" ");
	return rest.length > 0 ? { mode: "set", change, ignored: rest } : { mode: "set", change };
}

/**
 * Normalize an opsx gate report into a stable stall key: the SORTED set of
 * `GATE-FAIL <check_id>` identifiers, excluding volatile content (paths, SHAs,
 * timestamps, free-text messages). Used to detect a genuinely repeating failure.
 * (opsx-loop.stall-detection-stops-the-loop)
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
 * Parse the normalized doneness GAP SET from a `doneness.md` body: the bullets
 * under the `## Gaps` heading, lowercased / markup-stripped / whitespace-collapsed
 * and de-duplicated + sorted for stable set comparison. Template placeholder bullets
 * (`- <...>`) and an absent/gap-less file yield the EMPTY set (the sentinel).
 * (opsx-loop.stall-detection-stops-the-loop)
 */
export function parseDonenessGaps(md: string): string[] {
	const lines = (md ?? "").split(/\r?\n/);
	const gaps: string[] = [];
	let inGaps = false;
	for (const line of lines) {
		if (/^#{1,6}\s+/.test(line)) {
			inGaps = /^#{1,6}\s+gaps\b/i.test(line);
			continue;
		}
		if (!inGaps) continue;
		const m = line.match(/^\s*[-*]\s+(.*\S)\s*$/);
		if (!m) continue;
		const norm = m[1]
			.replace(/<!--[\s\S]*?-->/g, "")
			.replace(/[`*_]/g, "")
			.toLowerCase()
			.replace(/\s+/g, " ")
			.trim();
		if (norm.length > 0 && !norm.startsWith("<")) gaps.push(norm);
	}
	return Array.from(new Set(gaps)).sort();
}

/**
 * Classify a doneness.md body for stall routing. `satisfied` (a sealed satisfied
 * verdict that the gate nonetheless failed on freshness/provenance) routes to the
 * ORDINARY content/HEAD progress signal (re-judged next turn); `gap` (a `not`
 * verdict, or an absent/unparseable file) routes to the bounded gap-set ratchet.
 * HTML comments are stripped so a template comment cannot satisfy the match.
 * (opsx-loop.stall-detection-stops-the-loop)
 */
export function classifyDoneness(md: string | null): "satisfied" | "gap" {
	if (md == null) return "gap";
	const stripped = md.replace(/<!--[\s\S]*?-->/g, "");
	const m = stripped.match(/^[*_ ]*Doneness[*_ ]*:[*_ ]*([A-Za-z]+)/im);
	return m && m[1].toLowerCase() === "satisfied" ? "satisfied" : "gap";
}

/**
 * Running-minimum gap-set ratchet. Progress is counted ONLY when `current` is a
 * NON-EMPTY proper subset of the smallest gap set seen this streak (`min`) with
 * strictly fewer members; such a reduction updates the running minimum. The
 * empty-set sentinel (absent/unparseable doneness.md) is NEVER progress and NEVER
 * overwrites `min`. Growth, equal-cardinality swaps, oscillation down-swings to a
 * seen set, and rewords to the same normalized membership are all not-progress, so
 * an agent that churns files without monotonically closing judged gaps trips the
 * stall instead of looping forever under an unbounded budget.
 * (opsx-loop.stall-detection-stops-the-loop)
 */
export function donenessRatchet(
	min: string[] | undefined,
	current: string[],
): { progress: boolean; min: string[] | undefined } {
	if (current.length === 0) return { progress: false, min }; // ∅ sentinel: no progress, no overwrite
	if (min === undefined) return { progress: false, min: current.slice() }; // establish baseline
	const minSet = new Set(min);
	const properSubset = current.length < min.length && current.every((g) => minSet.has(g));
	return properSubset ? { progress: true, min: current.slice() } : { progress: false, min };
}

/**
 * Verdict from an opsx gate run: exit 0 = met, any non-zero (or failure to
 * execute) = not met, with the gate's combined output as the reason.
 * Pure; never throws. (opsx-loop.opsx-gate-is-the-deterministic-judge)
 */
export function verdictFromExit(code: number | null, output: string): LoopVerdict {
	const out = (output ?? "").trim();
	if (code === 0) return { met: true, reason: out.slice(0, 2000) || "opsx gate exited 0" };
	return { met: false, reason: out.slice(0, 2000) || `opsx gate exited ${code ?? "non-zero"}` };
}

/**
 * Parse `loop_max_iterations` from a change's review.md YAML front-matter
 * (between the first two '---' fences). Falls back to `def` when absent or
 * unparseable. (opsx-loop.budget-from-review-front-matter)
 */
/**
 * The configured loop budget from review.md front-matter `loop_max_iterations`,
 * or undefined when unconfigured. undefined means NO budget (unbounded) — the
 * loop then stops only on gate-green, stall detection, abort, or manual clear.
 * (opsx-loop.budget-from-review-front-matter)
 */
/**
 * Orchestrator-settable landing hold from review.md front-matter.
 * `loop_hold: true` (anchored, unquoted) holds; anything else does not.
 * The hold is honored even when the reason is empty — a malformed landing must
 * still land (fail-safe direction; clarify C1).
 * (opsx-loop.loop-hold-blocks-continuation)
 */
export interface LoopHold {
	held: boolean;
	reason: string;
}
export function parseLoopHold(reviewMd: string): LoopHold {
	const text = reviewMd ?? "";
	const lines = text.split(/\r?\n/);
	if (lines[0]?.trim() !== "---") return { held: false, reason: "" };
	let held = false;
	let reason = "";
	for (let i = 1; i < lines.length; i++) {
		if (lines[i].trim() === "---") break;
		if (/^\s*loop_hold\s*:\s*true\s*$/i.test(lines[i])) held = true;
		const m = lines[i].match(/^\s*loop_hold_reason\s*:\s*(.*?)\s*$/);
		if (m) reason = m[1].replace(/^["']|["']$/g, "");
	}
	return { held, reason };
}

/**
 * Strip the loop_hold fields from review.md front-matter (named re-arm clears
 * the hold; goal kickoff never calls this). Returns the text unchanged when no
 * hold fields are present. (opsx-loop.loop-hold-blocks-continuation)
 */
export function stripLoopHold(reviewMd: string): string {
	const text = reviewMd ?? "";
	const lines = text.split(/\r?\n/);
	if (lines[0]?.trim() !== "---") return text;
	const out: string[] = [];
	let inFm = true;
	for (let i = 0; i < lines.length; i++) {
		if (i > 0 && inFm && lines[i].trim() === "---") inFm = false;
		if (i > 0 && inFm && /^\s*loop_hold(_reason)?\s*:/.test(lines[i])) continue;
		out.push(lines[i]);
	}
	return out.join("\n");
}

/**
 * The full named-re-arm clearing transform: strip the hold fields and append
 * the auditable clearance line under Execution Notes (created when absent).
 * Pure text→text so the extension's file write is a dumb persist.
 * (opsx-loop.loop-hold-blocks-continuation)
 */
export function clearHoldText(reviewMd: string, change: string, dateStr: string): { next: string; reason: string } {
	const hold = parseLoopHold(reviewMd);
	let next = stripLoopHold(reviewMd);
	const noteLine = `- ${dateStr} — loop_hold cleared by named re-arm (/opsx-loop ${change}); reason was: ${hold.reason || "(none recorded)"}`;
	// Line-anchored heading + replacement FUNCTION: a reason containing `$&`-style
	// patterns must not corrupt the note, and a longer heading ("## Execution Notes
	// (archived)") must not be spliced into.
	const heading = /^## Execution Notes\s*$/m;
	next = heading.test(next)
		? next.replace(heading, () => `## Execution Notes\n\n${noteLine}`)
		: `${next}\n\n## Execution Notes\n\n${noteLine}\n`;
	return { next, reason: hold.reason };
}

/**
 * Deterministic active-change inventory for the distill kickoff directive:
 * names of change dirs (non-archive) carrying a committed intent.md, with the
 * cheap front-matter scale as status. Directory listing + front-matter parse
 * ONLY — no gate runs, no model calls.
 * (opsx-loop.goal-and-conversation-kickoff)
 */
export interface InventoryEntry {
	name: string;
	scale: string;
}
export function listIntentChanges(cwd: string, isCommitted?: (name: string) => boolean): InventoryEntry[] {
	try {
		const base = join(cwd, "openspec", "changes");
		return readdirSync(base, { withFileTypes: true })
			.filter(
				(e) =>
					e.isDirectory() &&
					e.name !== "archive" &&
					existsSync(join(base, e.name, "intent.md")) &&
					// Spec: inventory lists changes with a COMMITTED intent.md — a
					// working-tree draft is not a resumable baseline. The predicate is
					// injected (git ls-files in the extension) to keep this pure.
					(isCommitted === undefined || isCommitted(e.name)),
			)
			.map((e) => {
				let scale = "?";
				try {
					const review = readFileSync(join(base, e.name, "review.md"), "utf-8");
					const lines = review.split(/\r?\n/);
					if (lines[0]?.trim() === "---") {
						for (let i = 1; i < lines.length; i++) {
							if (lines[i].trim() === "---") break;
							const m = lines[i].match(/^\s*scale\s*:\s*(\S+)\s*$/);
							if (m) {
								scale = m[1];
								break;
							}
						}
					}
				} catch {
					/* no review.md yet — status stays "?" */
				}
				return { name: e.name, scale };
			})
			.sort((a, b) => a.name.localeCompare(b.name));
	} catch {
		return [];
	}
}

/** Render the inventory block for the distill KICKOFF directive (never the continuation nudge). */
export function formatInventory(entries: InventoryEntry[]): string {
	if (entries.length === 0) return "(none)";
	return entries.map((e) => `  - ${e.name} (scale: ${e.scale})`).join("\n");
}

export function parseLoopBudget(reviewMd: string): number | undefined {
	const text = reviewMd ?? "";
	const lines = text.split(/\r?\n/);
	if (lines[0]?.trim() !== "---") return undefined;
	for (let i = 1; i < lines.length; i++) {
		if (lines[i].trim() === "---") break;
		// The WHOLE value must be a positive integer (anchored): `80junk`, `-1`,
		// `abc80`, quoted values are unparseable and yield undefined (unbounded),
		// per the spec's "absent or unparseable => budget unset" contract.
		const m = lines[i].match(/^\s*loop_max_iterations\s*:\s*(\d+)\s*$/);
		if (m) {
			const n = Number.parseInt(m[1], 10);
			if (Number.isFinite(n) && n > 0) return n;
		}
		if (/^\s*loop_max_iterations\s*:/.test(lines[i])) return undefined;
	}
	return undefined;
}

// ── Proactive between-turns compaction threshold (Lever A) ──────────────────
// The loop is the operator's SOLE compaction path (pi auto-compaction is off), so
// this is DEFAULT-ON. The trigger, in absolute tokens, is the HIGHER of a percent
// of the context window and an absolute floor: max(33% * window, 100_000). Either
// term is independently configurable via env and can be turned off; with BOTH off
// the feature is disabled.

const OFF_TOKENS = new Set(["off", "none", "false", "0"]);

/**
 * Resolve the PERCENT term of the compaction trigger from `OPSX_COMPACT_AT_PERCENT`.
 * Returns an integer 1..100, or null when the term is explicitly OFF
 * (`off`/`none`/`false`/`0`). Unset or garbage falls back to the default 33 — the
 * feature is default-on, so an unparseable value must NOT silently disable it.
 */
export function resolveCompactPercent(raw: string | undefined): number | null {
	if (raw == null || raw.trim() === "") return 33;
	const t = raw.trim().toLowerCase();
	if (OFF_TOKENS.has(t)) return null;
	if (!/^\d+$/.test(t)) return 33;
	const n = Number.parseInt(t, 10);
	if (n < 1 || n > 100) return 33;
	return n;
}

/**
 * Resolve the ABSOLUTE-TOKEN floor term from `OPSX_COMPACT_AT_TOKENS`.
 * Returns a positive integer, or null when explicitly OFF. Unset or garbage falls
 * back to the default 100_000.
 */
export function resolveCompactTokens(raw: string | undefined): number | null {
	if (raw == null || raw.trim() === "") return 100_000;
	const t = raw.trim().toLowerCase();
	if (OFF_TOKENS.has(t)) return null;
	if (!/^\d+$/.test(t)) return 100_000;
	const n = Number.parseInt(t, 10);
	if (n < 1) return 100_000;
	return n;
}

/**
 * Resolve the absolute token count at/above which the loop compacts BEFORE the
 * next worker turn: max(percentTerm * window, tokenFloor). Either term may be OFF;
 * with BOTH off (or a non-positive window and the floor off) the feature is
 * disabled and this returns undefined. Default (both unset): max(33% window, 100k).
 */
export function resolveCompactThresholdTokens(
	contextWindow: number,
	pctRaw: string | undefined,
	tokRaw: string | undefined,
): number | undefined {
	const pct = resolveCompactPercent(pctRaw);
	const tok = resolveCompactTokens(tokRaw);
	const terms: number[] = [];
	if (pct != null && Number.isFinite(contextWindow) && contextWindow > 0) {
		terms.push(Math.ceil((pct / 100) * contextWindow));
	}
	if (tok != null) terms.push(tok);
	if (terms.length === 0) return undefined;
	return Math.max(...terms);
}

/** One-line human description of the active policy for the loop-arm notify. */
export function describeCompactPolicy(pctRaw: string | undefined, tokRaw: string | undefined): string {
	const pct = resolveCompactPercent(pctRaw);
	const tok = resolveCompactTokens(tokRaw);
	if (pct == null && tok == null) return "compaction guard: off";
	const parts: string[] = [];
	if (pct != null) parts.push(`${pct}% window`);
	if (tok != null) parts.push(`${tok.toLocaleString("en-US")} tokens`);
	return `compaction guard: compact at ≥ ${parts.join(" or ")} (whichever higher)`;
}
