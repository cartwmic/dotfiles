// Unit tests for goal-loop pure helpers.
// Acceptance criteria cited by canonical ID for the opsx verify gate:
//   goal-loop.handle-evaluation-failure
//   goal-loop.clear-a-goal
//   goal-loop.bound-the-loop-with-a-turn-budget
//   goal-loop.evaluate-each-turn-once
import { describe, expect, test } from "bun:test";
import { decideAfterEvaluation, parseGoalArg, parseVerdict, shouldStopForBudget } from "./helpers.ts";

describe("parseVerdict — goal-loop.handle-evaluation-failure", () => {
	test("clean JSON object", () => {
		const v = parseVerdict('{"met": true, "reason": "all tests pass"}');
		expect(v.met).toBe(true);
		expect(v.reason).toBe("all tests pass");
	});

	test("JSON embedded in prose still parses", () => {
		const v = parseVerdict('Here is my verdict: {"met": false, "reason": "lint failed"} done');
		expect(v.met).toBe(false);
		expect(v.reason).toBe("lint failed");
	});

	test("garbage defaults to not-met with raw text as reason", () => {
		const v = parseVerdict("I think it is probably fine?");
		expect(v.met).toBe(false);
		expect(v.reason).toContain("probably fine");
	});

	test("empty input is non-fatal and not-met", () => {
		const v = parseVerdict("");
		expect(v.met).toBe(false);
		expect(typeof v.reason).toBe("string");
	});

	test("non-boolean met coerces to not-met", () => {
		const v = parseVerdict('{"met": "yes", "reason": "x"}');
		expect(v.met).toBe(false);
	});
});

describe("parseGoalArg — goal-loop.clear-a-goal", () => {
	test("empty arg is status", () => {
		expect(parseGoalArg("").mode).toBe("status");
		expect(parseGoalArg("   ").mode).toBe("status");
	});

	test("clear and all aliases", () => {
		for (const a of ["clear", "stop", "off", "reset", "none", "cancel", "CLEAR", "  Stop "]) {
			expect(parseGoalArg(a).mode).toBe("clear");
		}
	});

	test("non-empty condition is set", () => {
		const r = parseGoalArg("all tests in test/auth pass");
		expect(r.mode).toBe("set");
		expect(r.condition).toBe("all tests in test/auth pass");
	});

	test("a condition that merely contains an alias word is still set", () => {
		expect(parseGoalArg("stop the flaky tests from failing").mode).toBe("set");
	});
});

describe("shouldStopForBudget — goal-loop.bound-the-loop-with-a-turn-budget / evaluate-each-turn-once", () => {
	test("stops once elapsed turns reach the budget", () => {
		expect(shouldStopForBudget(25, 25)).toBe(true);
		expect(shouldStopForBudget(26, 25)).toBe(true);
	});

	test("continues while under budget", () => {
		expect(shouldStopForBudget(1, 25)).toBe(false);
		expect(shouldStopForBudget(24, 25)).toBe(false);
	});
});

describe("decideAfterEvaluation — goal-loop.complete-when-condition-met / continue-when-condition-not-met", () => {
	test("met wins even when the budget is reached on the same turn (clarify I1)", () => {
		expect(decideAfterEvaluation({ turns: 4, maxTurns: 4 }, { met: true, reason: "ok" })).toBe("achieved");
	});

	test("not-met at budget → exhausted", () => {
		expect(decideAfterEvaluation({ turns: 4, maxTurns: 4 }, { met: false, reason: "nope" })).toBe("exhausted");
	});

	test("not-met under budget → continue", () => {
		expect(decideAfterEvaluation({ turns: 2, maxTurns: 4 }, { met: false, reason: "nope" })).toBe("continue");
	});

	test("met under budget → achieved", () => {
		expect(decideAfterEvaluation({ turns: 1, maxTurns: 4 }, { met: true, reason: "done" })).toBe("achieved");
	});
});
