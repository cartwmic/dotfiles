// Unit tests for opsx-loop pure helpers.
// Acceptance criteria cited by canonical ID for the opsx verify gate:
//   opsx-loop-kickoff.opsx-gate-is-the-deterministic-judge
//   opsx-loop-kickoff.budget-from-review-front-matter
//   opsx-loop-kickoff.status-and-clear-subcommands
import { describe, expect, test } from "bun:test";
import { parseLoopArg, parseLoopBudget, verdictFromExit } from "./helpers.ts";

describe("verdictFromExit — opsx-loop-kickoff.opsx-gate-is-the-deterministic-judge", () => {
	test("exit 0 is met", () => {
		expect(verdictFromExit(0, "GATE-PASS: x (M)")).toEqual({ met: true, reason: "GATE-PASS: x (M)" });
	});
	test("exit 0 empty output still met", () => {
		expect(verdictFromExit(0, "  ")).toEqual({ met: true, reason: "opsx-gate exited 0" });
	});
	test("non-zero is not met, report surfaced", () => {
		expect(verdictFromExit(1, "GATE-FAIL tasks 1 3 unchecked")).toEqual({
			met: false,
			reason: "GATE-FAIL tasks 1 3 unchecked",
		});
	});
	test("non-zero empty output reports code", () => {
		expect(verdictFromExit(2, "")).toEqual({ met: false, reason: "opsx-gate exited 2" });
	});
	test("null code (spawn failure) is not met", () => {
		expect(verdictFromExit(null, "").met).toBe(false);
	});
});

describe("parseLoopBudget — opsx-loop-kickoff.budget-from-review-front-matter", () => {
	const fm = (n: string) => `---\nscale: M\nloop_max_iterations: ${n}\n---\n# Review\n`;
	test("reads loop_max_iterations from front-matter", () => {
		expect(parseLoopBudget(fm("80"))).toBe(80);
	});
	test("defaults when absent", () => {
		expect(parseLoopBudget("---\nscale: M\n---\n")).toBe(40);
	});
	test("defaults when no front-matter", () => {
		expect(parseLoopBudget("# Review\nloop_max_iterations: 99\n")).toBe(40);
	});
	test("ignores non-positive / non-numeric", () => {
		expect(parseLoopBudget(fm("0"))).toBe(40);
		expect(parseLoopBudget("---\nloop_max_iterations: abc\n---")).toBe(40);
	});
	test("custom default honored", () => {
		expect(parseLoopBudget("", 25)).toBe(25);
	});
});

describe("parseLoopArg — opsx-loop-kickoff.status-and-clear-subcommands", () => {
	test("empty → status", () => {
		expect(parseLoopArg("")).toEqual({ mode: "status" });
	});
	test("status / ? keywords", () => {
		expect(parseLoopArg("status")).toEqual({ mode: "status" });
		expect(parseLoopArg("?")).toEqual({ mode: "status" });
	});
	test("clear and aliases", () => {
		for (const a of ["clear", "stop", "off", "reset", "none", "cancel"]) {
			expect(parseLoopArg(a)).toEqual({ mode: "clear" });
		}
	});
	test("a change name is a set (first token)", () => {
		expect(parseLoopArg("add-clipboard-extension")).toEqual({ mode: "set", change: "add-clipboard-extension" });
		expect(parseLoopArg("  my-change  extra ")).toEqual({ mode: "set", change: "my-change" });
	});
	test("change name containing a keyword is still a set", () => {
		expect(parseLoopArg("stop-the-flaky-tests")).toEqual({ mode: "set", change: "stop-the-flaky-tests" });
	});
});
