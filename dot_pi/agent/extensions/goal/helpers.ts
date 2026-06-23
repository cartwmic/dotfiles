// Pure, dependency-free helpers for the goal-loop extension.
// Kept free of pi-runtime imports so they are unit-testable via `bun test`.

export interface Verdict {
	met: boolean;
	reason: string;
}

const CLEAR_ALIASES = new Set(["clear", "stop", "off", "reset", "none", "cancel"]);
const STATUS_KEYWORDS = new Set(["status", "?"]);

/** Subcommand suggestions for argument autocomplete. */
export const GOAL_SUBCOMMANDS: ReadonlyArray<{ value: string; label: string; description: string }> = [
	{ value: "status", label: "status", description: "Show the active goal's condition, turns, and last verdict" },
	{ value: "clear", label: "clear", description: "Stop and clear the active goal (aliases: stop, off, reset, none, cancel)" },
];

export type GoalArg =
	| { mode: "status" }
	| { mode: "clear" }
	| { mode: "set"; condition: string };

/**
 * Classify the `/goal` argument.
 * - empty / whitespace             → status
 * - exactly "status" or "?"         → status
 * - exactly a clear alias          → clear
 * - anything else                  → set (the trimmed text is the condition)
 *
 * Matching is exact (case-insensitive, trimmed) so a condition that merely
 * contains a keyword (e.g. "stop the flaky tests", "check status of x") is
 * still a set.
 */
export function parseGoalArg(raw: string): GoalArg {
	const arg = (raw ?? "").trim();
	if (arg.length === 0) return { mode: "status" };
	const lower = arg.toLowerCase();
	if (STATUS_KEYWORDS.has(lower)) return { mode: "status" };
	if (CLEAR_ALIASES.has(lower)) return { mode: "clear" };
	return { mode: "set", condition: arg };
}

/**
 * Tolerantly parse an evaluator verdict.
 * Extracts the first balanced-looking JSON object; on any failure defaults to
 * not-met with the raw text as the reason. Never throws.
 * (goal-loop.handle-evaluation-failure)
 */
export function parseVerdict(text: string): Verdict {
	const raw = (text ?? "").trim();
	const fallback: Verdict = {
		met: false,
		reason: raw.length > 0 ? raw.slice(0, 500) : "empty or unparseable verdict",
	};

	const start = raw.indexOf("{");
	const end = raw.lastIndexOf("}");
	if (start === -1 || end === -1 || end <= start) return fallback;

	try {
		const obj = JSON.parse(raw.slice(start, end + 1));
		if (typeof obj !== "object" || obj === null) return fallback;
		const met = obj.met === true; // strict: only a real boolean true counts as met
		const reason =
			typeof obj.reason === "string" && obj.reason.trim().length > 0
				? obj.reason.trim()
				: fallback.reason;
		return { met, reason };
	} catch {
		return fallback;
	}
}

/**
 * Build a verdict from a submit_verdict tool call's arguments (the bridge
 * "capture" path). Returns undefined when the args are not a valid verdict,
 * so the caller can fall back to free-text parsing.
 */
export function verdictFromToolArgs(args: unknown): Verdict | undefined {
	if (typeof args !== "object" || args === null) return undefined;
	const a = args as Record<string, unknown>;
	if (typeof a.met !== "boolean") return undefined;
	const reason =
		typeof a.reason === "string" && a.reason.trim().length > 0 ? a.reason.trim() : "(no reason given)";
	return { met: a.met, reason };
}

/**
 * Whether the loop must stop because the turn budget is exhausted.
 * `turns` is the count of evaluated turns (incremented once per evaluation,
 * including the initial set turn — clarify A2).
 * (goal-loop.bound-the-loop-with-a-turn-budget)
 */
export function shouldStopForBudget(turns: number, maxTurns: number): boolean {
	return turns >= maxTurns;
}

export interface GoalConfig {
	judgeModel?: string;
	judgeCommand?: string;
	maxTurns?: number;
}

/**
 * Verdict from a command judge: exit 0 = met, any non-zero (or failure to
 * execute) = not met, with the command's output surfaced as the reason.
 * Pure; never throws. The goal-loop stays agnostic to what the command checks.
 * (goal-loop.pluggable-command-judge)
 */
export function commandVerdict(code: number | null, output: string): Verdict {
	const out = (output ?? "").trim();
	if (code === 0) {
		return { met: true, reason: out.slice(0, 2000) || "judge command exited 0" };
	}
	return { met: false, reason: out.slice(0, 2000) || `judge command exited ${code ?? "non-zero"}` };
}

/**
 * Normalize an untrusted parsed config.json into a GoalConfig.
 * Invalid/missing fields are dropped (never throws).
 */
export function normalizeGoalConfig(raw: unknown): GoalConfig {
	const out: GoalConfig = {};
	if (typeof raw !== "object" || raw === null) return out;
	const obj = raw as Record<string, unknown>;
	if (typeof obj.judgeModel === "string" && obj.judgeModel.trim().length > 0) {
		out.judgeModel = obj.judgeModel.trim();
	}
	if (typeof obj.judgeCommand === "string" && obj.judgeCommand.trim().length > 0) {
		out.judgeCommand = obj.judgeCommand.trim();
	}
	if (typeof obj.maxTurns === "number" && Number.isFinite(obj.maxTurns) && obj.maxTurns > 0) {
		out.maxTurns = Math.floor(obj.maxTurns);
	}
	return out;
}

/**
 * Resolve a setting by precedence: env var (highest) > config file > default.
 * Empty/whitespace env values are ignored.
 */
export function resolveSetting<T>(
	envValue: string | undefined,
	parseEnv: (s: string) => T | undefined,
	configValue: T | undefined,
	defaultValue: T,
): T {
	if (envValue && envValue.trim().length > 0) {
		const parsed = parseEnv(envValue.trim());
		if (parsed !== undefined) return parsed;
	}
	if (configValue !== undefined) return configValue;
	return defaultValue;
}

export interface AssistantInfo {
	text: string;
	stopReason?: string;
}

/**
 * Extract the latest assistant message's text + stopReason from a run's
 * message list. stopReason "aborted" means the user interrupted the turn;
 * "error" means the turn failed. Pure / never throws.
 */
export function lastAssistantInfo(messages: unknown): AssistantInfo {
	if (!Array.isArray(messages)) return { text: "" };
	for (let i = messages.length - 1; i >= 0; i--) {
		const m = messages[i] as any;
		if (m?.role === "assistant") {
			const text = Array.isArray(m.content)
				? m.content
						.filter((c: any) => c?.type === "text")
						.map((c: any) => c.text)
						.join("\n")
						.trim()
				: "";
			return { text, stopReason: typeof m.stopReason === "string" ? m.stopReason : undefined };
		}
	}
	return { text: "" };
}

/** A turn the user interrupted or that errored should not auto-continue. */
export function isInterruptedStop(stopReason: string | undefined): boolean {
	return stopReason === "aborted" || stopReason === "error";
}

export type LoopAction = "achieved" | "exhausted" | "continue";

/**
 * Decide what the loop does after one evaluation. Pure branching logic —
 * the IO (notify, sendUserMessage, clear) is wired around this in index.ts.
 *
 * `turns` is already incremented for the just-evaluated turn.
 * Met wins over a simultaneously-reached budget (clarify I1): the budget
 * cutoff is only consulted when the verdict is not-met.
 * (goal-loop.complete-when-condition-met,
 *  goal-loop.bound-the-loop-with-a-turn-budget,
 *  goal-loop.continue-when-condition-not-met)
 */
export function decideAfterEvaluation(
	state: { turns: number; maxTurns: number },
	verdict: Verdict,
): LoopAction {
	if (verdict.met) return "achieved";
	if (shouldStopForBudget(state.turns, state.maxTurns)) return "exhausted";
	return "continue";
}
