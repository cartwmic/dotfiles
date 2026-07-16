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

/** Generic subagent tool name muted while an opsx-loop is armed. */
export const SUBAGENT_TOOL_NAME = "subagent";

/** Loop-scoped role-dispatch tool activated while an opsx-loop is armed. */
export const OPSX_DISPATCH_TOOL_NAME = "opsx_dispatch";

/**
 * Build the active tool set for an armed loop: drop `subagent`, ensure
 * `opsx_dispatch` is present, preserve other tools from the pre-arm snapshot.
 * (opsx-loop.armed-loop-mutes-generic-subagent-tool)
 */
export function applyArmedToolSet(toolsBeforeArm: string[]): string[] {
	const out: string[] = [];
	const seen = new Set<string>();
	for (const name of toolsBeforeArm) {
		if (name === SUBAGENT_TOOL_NAME || name === OPSX_DISPATCH_TOOL_NAME) continue;
		if (seen.has(name)) continue;
		seen.add(name);
		out.push(name);
	}
	if (!seen.has(OPSX_DISPATCH_TOOL_NAME)) {
		out.push(OPSX_DISPATCH_TOOL_NAME);
	}
	return out;
}

/**
 * Restore tools after clear/stop. Prefer the exact pre-arm snapshot; if absent,
 * drop `opsx_dispatch` from the current set (fail-safe disarmed state).
 * (opsx-loop.armed-loop-mutes-generic-subagent-tool)
 */
export function restoreToolSetAfterClear(
	toolsBeforeArm: string[] | undefined,
	currentActive: string[],
): string[] {
	if (toolsBeforeArm !== undefined) return [...toolsBeforeArm];
	return currentActive.filter((n) => n !== OPSX_DISPATCH_TOOL_NAME);
}

export type OpsxDispatchRole = "review" | "impl" | "author";

export interface OpsxDispatchSpawnSpec {
	model: string;
	task: string;
	agent: string;
}

export type OpsxDispatchPlan =
	| { ok: false; reason: "not-armed" | "unset" | "author-in-session"; message: string }
	| { ok: true; spawns: OpsxDispatchSpawnSpec[] };

function roleConfigured(r: ResolvedModel | null | undefined): r is ResolvedModel {
	return r != null && r.source !== "unset" && r.source !== "default" && r.value != null;
}

function modelListFromResolved(r: ResolvedModel): string[] {
	const v = r.value;
	if (Array.isArray(v)) return v.filter((x): x is string => typeof x === "string" && x.length > 0);
	if (typeof v === "string" && v.length > 0) return [v];
	return [];
}

/**
 * Pure planner for opsx_dispatch: armed-only, unset=refuse, role sole model
 * source (caller model ignored), review auto fan-out.
 * (opsx-loop.opsx-dispatch-forces-resolved-role-model,
 *  opsx-loop.review-role-auto-fan-out)
 */
export function planOpsxDispatch(input: {
	armed: boolean;
	role: OpsxDispatchRole;
	task: string;
	agent?: string;
	/** Ignored when role is configured — documented for callers. */
	callerModel?: string;
	resolved: ResolvedModel | null;
	/** When role=author and this is true/undefined, refuse (in-session default). */
	authorInSession?: boolean | null;
}): OpsxDispatchPlan {
	if (!input.armed) {
		return {
			ok: false,
			reason: "not-armed",
			message:
				"opsx_dispatch refused: no opsx-loop is armed. Use /opsx-loop <change> first, or the generic subagent tool when disarmed.",
		};
	}
	if (input.role === "author" && input.authorInSession !== false) {
		return {
			ok: false,
			reason: "author-in-session",
			message:
				'opsx_dispatch refused: author role is in-session by default. Set author-in-session false (opsx models / review.md) before delegating author via opsx_dispatch.',
		};
	}
	if (!roleConfigured(input.resolved)) {
		return {
			ok: false,
			reason: "unset",
			message: `opsx_dispatch refused: role "${input.role}" is unset. Configure it with \`opsx models set ${input.role}\` (or change/user/env layers). No session-model fallback on this path.`,
		};
	}
	const models = modelListFromResolved(input.resolved);
	if (models.length === 0) {
		return {
			ok: false,
			reason: "unset",
			message: `opsx_dispatch refused: role "${input.role}" resolved empty. Configure it with \`opsx models set ${input.role}\`.`,
		};
	}
	const agent = (input.agent && input.agent.trim()) || "worker";
	// callerModel intentionally unused — role is sole source
	void input.callerModel;
	return {
		ok: true,
		spawns: models.map((model) => ({ model, task: input.task, agent })),
	};
}

export interface OpsxDispatchSpawnResult {
	model: string;
	agent: string;
	ok: boolean;
	text: string;
}

/**
 * Run planned spawns via an injectable spawn fn (tests stub; production uses
 * pi-subagents runSync library). (opsx-loop.dispatch-spawns-via-subagent-library)
 */
export async function runOpsxDispatchSpawns(
	spawns: OpsxDispatchSpawnSpec[],
	spawnFn: (spec: OpsxDispatchSpawnSpec) => Promise<OpsxDispatchSpawnResult>,
): Promise<OpsxDispatchSpawnResult[]> {
	const out: OpsxDispatchSpawnResult[] = [];
	for (const spec of spawns) {
		out.push(await spawnFn(spec));
	}
	return out;
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
// this is DEFAULT-ON. The trigger is PERCENT-ONLY: a single percent of the live
// context window (default 50%), configured via `OPSX_COMPACT_AT_PERCENT`. Only the
// exact tokens off/none/false/0 disable the guard; garbage or out-of-range values
// fall back to the default — misconfiguration never silently disables compaction.
// The default 50 stays above the elision keep-recent budget (40%) so the levers
// layer: elide first, compact when elision can no longer hold total context down.
// (opsx-loop-compaction-guard)

const OFF_TOKENS = new Set(["off", "none", "false", "0"]);

/**
 * Resolve the compaction-trigger percent from `OPSX_COMPACT_AT_PERCENT`.
 * Returns an integer 1..100, or null when explicitly OFF
 * (`off`/`none`/`false`/`0`). Unset or garbage falls back to the default 50 — the
 * feature is default-on, so an unparseable value must NOT silently disable it.
 * (opsx-loop-compaction-guard.default-on-with-explicit-off-only,
 *  opsx-loop-compaction-guard.garbage-falls-back-to-default)
 */
export function resolveCompactPercent(raw: string | undefined): number | null {
	if (raw == null || raw.trim() === "") return 50;
	const t = raw.trim().toLowerCase();
	if (OFF_TOKENS.has(t)) return null;
	if (!/^\d+$/.test(t)) return 50;
	const n = Number.parseInt(t, 10);
	if (n < 1 || n > 100) return 50;
	return n;
}

/**
 * Resolve the absolute token count at/above which the loop compacts BEFORE the
 * next worker turn: ceil(percent/100 * window). Percent-only — there is no
 * absolute-token term. Returns undefined when the guard is explicitly OFF or the
 * context window is non-positive/unknown (caller skips the threshold decision).
 * (opsx-loop-compaction-guard.percent-only-compaction-trigger)
 */
export function resolveCompactThresholdTokens(
	contextWindow: number,
	pctRaw: string | undefined,
): number | undefined {
	const pct = resolveCompactPercent(pctRaw);
	if (pct == null) return undefined;
	if (!Number.isFinite(contextWindow) || contextWindow <= 0) return undefined;
	return Math.ceil((pct / 100) * contextWindow);
}


// ── Context-overflow detection (loop-local overflow-recovery) ───────────────
// The operator keeps pi auto-compaction OFF, which also disables pi's built-in
// compact-and-retry overflow recovery (agent-session `_checkCompaction` returns
// early when `!settings.enabled`). So the loop mirrors pi's overflow DETECTION
// (utils/overflow.ts) to drive a bounded, overflow-ONLY compact-and-retry — without
// re-enabling general auto-compaction. Patterns copied verbatim from pi-ai so the
// two detectors stay in agreement.
const OVERFLOW_PATTERNS: RegExp[] = [
	/prompt is too long/i,
	/request_too_large/i,
	/input is too long for requested model/i,
	/exceeds the context window/i,
	/exceeds (?:the )?(?:model'?s )?maximum context length(?: of [\d,]+ tokens?|\s*\([\d,]+\))/i,
	/input token count.*exceeds the maximum/i,
	/maximum prompt length is \d+/i,
	/reduce the length of the messages/i,
	/maximum context length is \d+ tokens/i,
	/exceeds (?:the )?maximum allowed input length of [\d,]+ tokens?/i,
	/input \(\d+ tokens\) is longer than the model'?s context length \(\d+ tokens\)/i,
	/exceeds the limit of \d+/i,
	/exceeds the available context size/i,
	/greater than the context length/i,
	/context window exceeds limit/i,
	/exceeded model token limit/i,
	/too large for model with \d+ maximum context length/i,
	/model_context_window_exceeded/i,
	/prompt too long; exceeded (?:max )?context length/i,
	/context[_ ]length[_ ]exceeded/i,
	/too many tokens/i,
	/token limit exceeded/i,
	/^4(?:00|13)\s*(?:status code)?\s*\(no body\)/i,
];
const NON_OVERFLOW_PATTERNS: RegExp[] = [
	/^(Throttling error|Service unavailable):/i,
	/rate limit/i,
	/too many requests/i,
];

/**
 * True when an assistant message represents a CONTEXT-OVERFLOW error/condition,
 * mirroring pi-ai `isContextOverflow`. Three cases: (1) `stopReason: "error"` whose
 * `errorMessage` matches an overflow pattern and no non-overflow (rate-limit) pattern;
 * (2) silent overflow — `stopReason: "stop"` but input+cacheRead exceeds the window;
 * (3) length-stop overflow — `stopReason: "length"` with zero output and input filling
 * ≥99% of the window. Defensive on shape: a message without errorMessage/usage simply
 * fails the relevant case, degrading to "not overflow" (→ normal stop handling).
 */
export function isContextOverflowError(message: any, contextWindow?: number): boolean {
	if (!message) return false;
	const stop = message.stopReason;
	const err = typeof message.errorMessage === "string" ? message.errorMessage : "";
	if (stop === "error" && err) {
		if (!NON_OVERFLOW_PATTERNS.some((p) => p.test(err)) && OVERFLOW_PATTERNS.some((p) => p.test(err))) {
			return true;
		}
	}
	const u = message.usage;
	if (contextWindow && contextWindow > 0 && u) {
		const input = (u.input ?? 0) + (u.cacheRead ?? 0);
		if (stop === "stop" && input > contextWindow) return true;
		if (stop === "length" && (u.output ?? 0) === 0 && input >= contextWindow * 0.99) return true;
	}
	return false;
}

/** One-line human description of the active policy for the loop-arm notify.
 *  (opsx-loop-compaction-guard.policy-notify-describes-single-term) */
export function describeCompactPolicy(pctRaw: string | undefined): string {
	const pct = resolveCompactPercent(pctRaw);
	if (pct == null) return "compaction guard: off";
	return `compaction guard: compact at ≥ ${pct}% window`;
}

// ── Mid-run context elision (Lever L3) ──────────────────────────────────────
// A per-request, ephemeral `context`-event transform that keeps an ACTIVE loop
// worker in its low-context / high-accuracy regime by eliding STALE tool-result
// BODIES from the view sent to the model — WITHOUT aborting the turn and WITHOUT
// mutating stored history. The 71%-of-context bloat measured on real runs is spent
// tool-output text the model already consumed; the most-recent turns that fit the
// token budget (maxKeep) stay full (working memory) and every tool-result MESSAGE
// is kept (pairing intact → no provider 400).
// Deterministic, no LLM call. All types are structurally matched to pi-ai's
// AgentMessage/ToolResultMessage so helpers.ts stays free of pi-runtime imports.

/** The stub body an elided tool result is replaced with. The "re-run to view"
 *  phrasing is a real recovery valve inside a resumable loop. */
export const ELIDE_STUB = "[output elided to conserve context — re-run to view]";

/** Structural subset of pi-ai `TextContent`/`ToolResultMessage`/`AgentMessage`
 *  needed by the pure elision pass (kept local to avoid a pi-runtime import). */
export interface ElideMessage {
	role?: string;
	content?: unknown;
	toolCallId?: string;
	toolName?: string;
	isError?: boolean;
	timestamp?: number;
	[k: string]: unknown;
}

/**
 * Resolve the KEEP-RECENT percent-of-window budget from
 * `OPSX_ELIDE_KEEP_RECENT_PERCENT`. Default 40 (hold the model's working context
 * near 40% of the window — below the context-rot-heavy zone — on any window size).
 * Garbage or out-of-range → default; there is NO absolute token floor.
 */
export function resolveElideKeepPercent(raw: string | undefined): number {
	if (raw == null || raw.trim() === "") return 40;
	const t = raw.trim();
	if (!/^\d+$/.test(t)) return 40;
	const n = Number.parseInt(t, 10);
	if (n < 1 || n > 100) return 40;
	return n;
}

/**
 * Resolve the token-band percent-of-window hysteresis from `OPSX_ELIDE_BAND_PERCENT`.
 * Default 5 (advance the elision boundary only every 5%-of-window of growth so the
 * slim prefix stays prompt-cache-stable across requests). Garbage/out-of-range →
 * default.
 */
export function resolveElideBandPercent(raw: string | undefined): number {
	if (raw == null || raw.trim() === "") return 5;
	const t = raw.trim();
	if (!/^\d+$/.test(t)) return 5;
	const n = Number.parseInt(t, 10);
	if (n < 1 || n > 100) return 5;
	return n;
}

/**
 * The KEEP-RECENT token budget `maxKeep` = keepPercent% × window (no absolute floor).
 * Dynamic per model. Returns undefined for a non-positive/unknown window (caller
 * degrades to pass-through).
 */
export function resolveElideMaxKeepTokens(
	contextWindow: number,
	pctRaw: string | undefined,
): number | undefined {
	if (!Number.isFinite(contextWindow) || contextWindow <= 0) return undefined;
	const pct = resolveElideKeepPercent(pctRaw);
	return Math.ceil((pct / 100) * contextWindow);
}

/**
 * The token-band width = bandPercent% × window (minimum 1). Returns undefined for a
 * non-positive/unknown window.
 */
export function resolveElideBandTokens(
	contextWindow: number,
	pctRaw: string | undefined,
): number | undefined {
	if (!Number.isFinite(contextWindow) || contextWindow <= 0) return undefined;
	const pct = resolveElideBandPercent(pctRaw);
	return Math.max(1, Math.ceil((pct / 100) * contextWindow));
}

/**
 * Deterministic per-message token estimate: textual content characters ÷ 4. No
 * tokenizer or model call. Counts `text`/`thinking` block strings, a string
 * `content`, and a tool-call `name` + JSON-serialized `arguments`, so a large
 * tool-call or tool-result body is sized realistically. Non-textual blocks
 * contribute 0.
 */
export function estimateMessageTokens(m: ElideMessage): number {
	const content = m?.content;
	let chars = 0;
	if (typeof content === "string") {
		chars = content.length;
	} else if (Array.isArray(content)) {
		for (const c of content as unknown[]) {
			const b = c as { text?: unknown; thinking?: unknown; name?: unknown; arguments?: unknown };
			if (typeof b?.text === "string") chars += b.text.length;
			if (typeof b?.thinking === "string") chars += b.thinking.length;
			if (typeof b?.name === "string") chars += b.name.length;
			if (b?.arguments != null) {
				try {
					chars += JSON.stringify(b.arguments).length;
				} catch {
					/* non-serializable → skip */
				}
			}
		}
	}
	return Math.ceil(chars / 4);
}

/**
 * Token-budget elision boundary (turn index): tool results in turns BEFORE this
 * index are eligible for body elision; turns at/after it (the kept-full recent
 * window) are sent whole. Sheds the OLDEST turns, oldest→newest, until the shed
 * prefix reaches a band-quantized shed FLOOR = `ceil((total - ceiling) / band) * band`
 * where `ceiling = maxKeep + band`. Two properties fall out simultaneously:
 *  - CORRECTNESS (frozen decision 1 / invariant): the shed floor is at least
 *    `total - ceiling`, so the kept-full window's estimate is ALWAYS at or below
 *    `ceiling` (the large stale tool dump gets shed even when it sits AFTER a small
 *    oldest turn) — the kept window is genuinely bytes-bounded regardless of turn
 *    sizes. The only carve-out is a single newest turn that alone exceeds the ceiling
 *    (never shed — the loop caps the boundary before the newest turn).
 *  - HYSTERESIS (frozen decision 3): the shed floor is quantized to `band` multiples,
 *    so it only advances when total crosses a band multiple; between crossings the
 *    boundary is byte-stable across requests (prompt-cache friendly), advancing a turn
 *    edge roughly once per band of new tokens.
 * In the normal case the kept-full window's estimate lands in `[maxKeep, maxKeep + band]`;
 * it can dip below `maxKeep` only in the extreme where the boundary turn is itself
 * large — the safe over-shed direction, never breaking pairing or the newest-turn
 * guarantee. Whenever elision fires (total > ceiling) at least the oldest turn is shed
 * (boundary ≥ 1) — never a fire-but-noop. Returns 0 (no elision) when total ≤ ceiling
 * (hysteresis hold / within budget) or when there is only one turn.
 */
export function tokenBudgetBoundary(
	messages: ElideMessage[],
	maxKeepTokens: number,
	bandTokens: number,
): number {
	if (!Array.isArray(messages) || messages.length === 0) return 0;
	// Per-turn token totals (turn index increments at each assistant message; leading
	// non-assistant messages and the first assistant share turn 0 — identical indexing
	// to elideToolResultBodies so the boundary lines up with its turnOf map).
	const perTurn: number[] = [];
	let turn = 0;
	let sawAssistant = false;
	for (let i = 0; i < messages.length; i++) {
		if (messages[i]?.role === "assistant") {
			if (sawAssistant) turn++;
			sawAssistant = true;
		}
		perTurn[turn] = (perTurn[turn] ?? 0) + estimateMessageTokens(messages[i]);
	}
	const totalTurns = perTurn.length;
	if (totalTurns <= 1) return 0; // never elide the only/newest turn
	const maxKeep = Number.isFinite(maxKeepTokens) && maxKeepTokens > 0 ? maxKeepTokens : 0;
	if (maxKeep <= 0) return 0;
	const band = Number.isFinite(bandTokens) && bandTokens >= 1 ? bandTokens : 1;
	const ceiling = maxKeep + band;
	let total = 0;
	for (const t of perTurn) total += t;
	if (total <= ceiling) return 0; // within budget + band → hysteresis hold
	// Minimum shed to bring the kept window at/below the ceiling, quantized UP to a band
	// multiple for cache-stable hysteresis (≥ the raw floor, so the bound always holds).
	const shedFloor = total - ceiling; // > 0
	const bandedShedFloor = Math.ceil(shedFloor / band) * band; // ≥ shedFloor, ≥ band
	// Shed oldest turns until the shed prefix reaches the banded floor; `boundary` is the
	// OLDEST kept turn index. Cap before the newest turn: if even all older turns cannot
	// reach the floor, the newest turn alone exceeds the ceiling — keep just it.
	let cum = 0;
	let boundary = 0;
	for (let t = 0; t < totalTurns - 1; t++) {
		cum += perTurn[t];
		boundary = t + 1;
		if (cum >= bandedShedFloor) break;
	}
	return boundary;
}

export interface ElideOptions {
	maxKeepTokens?: number;
	bandTokens?: number;
}

export interface ElideResult {
	messages: ElideMessage[];
	elided: boolean;
}

/**
 * Produce a NEW view of `messages` with the text bodies of tool-result messages in
 * turns before the token-budget boundary replaced by `ELIDE_STUB`. Turn index
 * increments at every `assistant` message (its tool results belong to that turn).
 * KEEPS every message (never drops one → `tool_call ↔ tool_result` pairing intact),
 * keeps tool calls, assistant/user text, thinking blocks, and the kept-full recent
 * tool results in full. NEVER mutates the input array or its message objects. Fail-closed:
 * any unexpected shape/throw returns the ORIGINAL array with `elided:false`.
 */
export function elideToolResultBodies(
	messages: ElideMessage[],
	opts: ElideOptions = {},
): ElideResult {
	try {
		if (!Array.isArray(messages) || messages.length === 0) {
			return { messages, elided: false };
		}

		// Assign a turn index to each message (increment when an assistant message
		// starts a new turn). Leading non-assistant messages are turn 0.
		const turnOf = new Array<number>(messages.length);
		let turn = 0;
		let sawAssistant = false;
		// Collect every tool-call id advertised by an assistant message so we can verify
		// pairing before emitting an elided view (fail-closed on an orphan tool result).
		const callIds = new Set<string>();
		for (let i = 0; i < messages.length; i++) {
			const mm = messages[i];
			const role = mm?.role;
			if (role === "assistant") {
				if (sawAssistant) turn++;
				sawAssistant = true;
				if (Array.isArray(mm?.content)) {
					for (const c of mm!.content as unknown[]) {
						const block = c as { type?: string; id?: unknown };
						if (block?.type === "toolCall" && typeof block.id === "string") {
							callIds.add(block.id);
						}
					}
				}
			}
			turnOf[i] = turn;
		}
		const boundary = tokenBudgetBoundary(
			messages,
			opts.maxKeepTokens ?? 0,
			opts.bandTokens ?? 1,
		);
		if (boundary <= 0) return { messages, elided: false };

		// Pairing integrity (fail-closed): every tool-result MUST reference a tool-call
		// present in the transcript. An orphan tool_result means the input is malformed;
		// eliding it anyway would emit a structurally-broken view (spec: "structural
		// guard trips" → return the original unchanged). This makes the guard reachable
		// rather than cosmetic.
		for (let i = 0; i < messages.length; i++) {
			const m = messages[i];
			if (m && m.role === "toolResult") {
				const id = m.toolCallId;
				if (typeof id !== "string" || !callIds.has(id)) {
					return { messages, elided: false };
				}
				// A tool_result whose content is not a well-formed block array is
				// structurally malformed; rather than elide valid siblings around it and
				// emit a partially-transformed view, fail closed on the WHOLE pass (spec:
				// "structural guard trips" → original unchanged).
				if (!Array.isArray(m.content)) {
					return { messages, elided: false };
				}
			}
		}

		let elided = false;
		const out = messages.slice();
		for (let i = 0; i < messages.length; i++) {
			const m = messages[i];
			if (
				m &&
				m.role === "toolResult" &&
				turnOf[i] < boundary &&
				Array.isArray(m.content)
			) {
				const hasText = (m.content as unknown[]).some(
					(c) => (c as { type?: string })?.type === "text",
				);
				const alreadyStub =
					(m.content as unknown[]).length === 1 &&
					(m.content[0] as { type?: string; text?: string })?.type === "text" &&
					(m.content[0] as { text?: string })?.text === ELIDE_STUB;
				if (hasText && !alreadyStub) {
					out[i] = { ...m, content: [{ type: "text", text: ELIDE_STUB }] };
					elided = true;
				} else {
					out[i] = m;
				}
			} else {
				out[i] = m;
			}
		}

		if (!elided) return { messages, elided: false };
		// Structural guard: same length (elided entries are the same object or a shallow
		// clone with only content swapped) — combined with the pairing check above, every
		// tool_result stays paired and the system prompt (not in this array) is preserved
		// by construction. Fail closed if the length invariant somehow broke.
		if (out.length !== messages.length) return { messages, elided: false };
		return { messages: out, elided: true };
	} catch {
		return { messages, elided: false };
	}
}
