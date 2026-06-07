// Pure, dependency-free helpers for the goal-loop extension.
// Kept free of pi-runtime imports so they are unit-testable via `bun test`.

export interface Verdict {
	met: boolean;
	reason: string;
}

const CLEAR_ALIASES = new Set(["clear", "stop", "off", "reset", "none", "cancel"]);

export type GoalArg =
	| { mode: "status" }
	| { mode: "clear" }
	| { mode: "set"; condition: string };

/**
 * Classify the `/goal` argument.
 * - empty / whitespace        → status
 * - exactly a clear alias     → clear
 * - anything else             → set (the trimmed text is the condition)
 *
 * Matching is exact (case-insensitive, trimmed) so a condition that merely
 * contains an alias word (e.g. "stop the flaky tests") is still a set.
 */
export function parseGoalArg(raw: string): GoalArg {
	const arg = (raw ?? "").trim();
	if (arg.length === 0) return { mode: "status" };
	if (CLEAR_ALIASES.has(arg.toLowerCase())) return { mode: "clear" };
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
 * Whether the loop must stop because the turn budget is exhausted.
 * `turns` is the count of evaluated turns (incremented once per evaluation,
 * including the initial set turn — clarify A2).
 * (goal-loop.bound-the-loop-with-a-turn-budget)
 */
export function shouldStopForBudget(turns: number, maxTurns: number): boolean {
	return turns >= maxTurns;
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
