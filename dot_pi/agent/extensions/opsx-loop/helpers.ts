// Pure, dependency-free helpers for the opsx-loop kickoff extension.
// Kept free of pi-runtime imports so they are unit-testable via `bun test`.
// The loop mechanism mirrors the validated goal-loop pattern (ADR-0001/0004)
// but this extension is independent — the goal extension is never modified.

export interface LoopVerdict {
	met: boolean;
	reason: string;
}

export const LOOP_SUBCOMMANDS: ReadonlyArray<{ value: string; label: string; description: string }> = [
	{ value: "status", label: "status", description: "Show the active loop's change, turns, and budget" },
	{ value: "clear", label: "clear", description: "Stop and clear the active loop (aliases: stop, off, reset, none, cancel)" },
];

const CLEAR_ALIASES = new Set(["clear", "stop", "off", "reset", "none", "cancel"]);
const STATUS_KEYWORDS = new Set(["status", "?"]);

export type LoopArg =
	| { mode: "status" }
	| { mode: "clear" }
	| { mode: "set"; change: string };

/**
 * Classify the `/opsx-loop` argument. Matching for status/clear is exact
 * (case-insensitive, trimmed) so a change name that merely contains a keyword
 * is still a set. (opsx-loop-kickoff.status-and-clear-subcommands)
 */
export function parseLoopArg(raw: string): LoopArg {
	const arg = (raw ?? "").trim();
	if (arg.length === 0) return { mode: "status" };
	const lower = arg.toLowerCase();
	if (STATUS_KEYWORDS.has(lower)) return { mode: "status" };
	if (CLEAR_ALIASES.has(lower)) return { mode: "clear" };
	// Take the first token as the change name (ignore trailing junk/flags).
	return { mode: "set", change: arg.split(/\s+/)[0] };
}

/**
 * Verdict from an opsx-gate run: exit 0 = met, any non-zero (or failure to
 * execute) = not met, with the gate's combined output as the reason.
 * Pure; never throws. (opsx-loop-kickoff.opsx-gate-is-the-deterministic-judge)
 */
export function verdictFromExit(code: number | null, output: string): LoopVerdict {
	const out = (output ?? "").trim();
	if (code === 0) return { met: true, reason: out.slice(0, 2000) || "opsx-gate exited 0" };
	return { met: false, reason: out.slice(0, 2000) || `opsx-gate exited ${code ?? "non-zero"}` };
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
