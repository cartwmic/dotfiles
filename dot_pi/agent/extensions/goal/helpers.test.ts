// Unit tests for goal-loop pure helpers.
// Acceptance criteria cited by canonical ID for the opsx verify gate:
//   goal-loop.handle-evaluation-failure
//   goal-loop.clear-a-goal
//   goal-loop.bound-the-loop-with-a-turn-budget
//   goal-loop.evaluate-each-turn-once
import { describe, expect, test } from "bun:test";
import {
	decideAfterEvaluation,
	isInterruptedStop,
	lastAssistantInfo,
	normalizeGoalConfig,
	parseGoalArg,
	parseVerdict,
	resolveSetting,
	shouldStopForBudget,
	verdictFromToolArgs,
} from "./helpers.ts";

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

describe("verdictFromToolArgs — goal-loop.judge-each-completed-turn (capture path)", () => {
	test("valid tool args become a verdict", () => {
		expect(verdictFromToolArgs({ met: true, reason: "echoed back" })).toEqual({ met: true, reason: "echoed back" });
		expect(verdictFromToolArgs({ met: false, reason: "  " })).toEqual({ met: false, reason: "(no reason given)" });
	});

	test("missing/invalid met → undefined (caller falls back to text parse)", () => {
		expect(verdictFromToolArgs({ reason: "x" })).toBeUndefined();
		expect(verdictFromToolArgs({ met: "yes", reason: "x" })).toBeUndefined();
		expect(verdictFromToolArgs(null)).toBeUndefined();
		expect(verdictFromToolArgs("nope")).toBeUndefined();
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

describe("normalizeGoalConfig / resolveSetting — goal-loop.configurable-judge-and-budget", () => {
	test("valid config fields are kept", () => {
		expect(normalizeGoalConfig({ judgeModel: "deepseek/deepseek-v4-flash", maxTurns: 10 })).toEqual({
			judgeModel: "deepseek/deepseek-v4-flash",
			maxTurns: 10,
		});
	});

	test("invalid/empty fields are dropped, never throws", () => {
		expect(normalizeGoalConfig({ judgeModel: "  ", maxTurns: -3 })).toEqual({});
		expect(normalizeGoalConfig(null)).toEqual({});
		expect(normalizeGoalConfig("nope")).toEqual({});
		expect(normalizeGoalConfig({ maxTurns: 4.9 })).toEqual({ maxTurns: 4 });
	});

	const num = (s: string) => {
		const n = Number.parseInt(s, 10);
		return Number.isFinite(n) && n > 0 ? n : undefined;
	};

	test("env overrides config overrides default", () => {
		expect(resolveSetting("7", num, 10, 25)).toBe(7); // env wins
		expect(resolveSetting(undefined, num, 10, 25)).toBe(10); // config wins
		expect(resolveSetting("", num, undefined, 25)).toBe(25); // default
		expect(resolveSetting("garbage", num, 10, 25)).toBe(10); // bad env falls through to config
	});

	test("string setting precedence (judge model)", () => {
		const id = (s: string) => s;
		expect(resolveSetting("anthropic/claude-haiku-4-5", id, "deepseek/x", "")).toBe("anthropic/claude-haiku-4-5");
		expect(resolveSetting(undefined, id, "deepseek/x", "")).toBe("deepseek/x");
	});
});

describe("lastAssistantInfo / isInterruptedStop — goal-loop.interrupt-stops-the-loop", () => {
	const mk = (role: string, text: string, stopReason?: string) => ({
		role,
		content: [{ type: "text", text }],
		stopReason,
	});

	test("returns latest assistant text + stopReason", () => {
		const info = lastAssistantInfo([mk("user", "hi"), mk("assistant", "working", "aborted")]);
		expect(info.text).toBe("working");
		expect(info.stopReason).toBe("aborted");
	});

	test("non-array / empty is safe", () => {
		expect(lastAssistantInfo(undefined)).toEqual({ text: "" });
		expect(lastAssistantInfo([])).toEqual({ text: "" });
	});

	test("aborted and error count as interrupted; stop/toolUse do not", () => {
		expect(isInterruptedStop("aborted")).toBe(true);
		expect(isInterruptedStop("error")).toBe(true);
		expect(isInterruptedStop("stop")).toBe(false);
		expect(isInterruptedStop("toolUse")).toBe(false);
		expect(isInterruptedStop(undefined)).toBe(false);
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
