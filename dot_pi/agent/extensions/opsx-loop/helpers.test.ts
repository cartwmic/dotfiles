// Unit tests for opsx-loop pure helpers.
// Acceptance criteria cited by canonical ID for the opsx verify gate:
//   opsx-loop-kickoff.opsx-gate-is-the-deterministic-judge
//   opsx-loop-kickoff.budget-from-review-front-matter
//   opsx-loop-kickoff.status-and-clear-subcommands
import { describe, expect, test } from "bun:test";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { buildModelEnv, classifyDoneness, donenessRatchet, gateFailKey, hashDir, parseDonenessGaps, parseLoopArg, parseLoopBudget, parseModelsJson, verdictFromExit } from "./helpers.ts";

describe("doneness stall helpers — opsx-loop-kickoff.stall-detection-stops-the-loop", () => {
	const DONE = (v: string, gaps: string[] = []) =>
		`# Doneness\n**Doneness:** ${v}\n**Judge:** m\n` +
		(gaps.length ? `## Gaps\n${gaps.map((g) => `- ${g}`).join("\n")}\n` : "");

	test("parseDonenessGaps extracts + normalizes + sorts the gap set", () => {
		expect(parseDonenessGaps(DONE("not", ["B gap", "a gap", "A GAP"]))).toEqual(["a gap", "b gap"]);
	});
	test("parseDonenessGaps: absent Gaps section / satisfied file → empty set", () => {
		expect(parseDonenessGaps(DONE("satisfied"))).toEqual([]);
		expect(parseDonenessGaps("")).toEqual([]);
	});
	test("parseDonenessGaps ignores template placeholder bullets", () => {
		expect(parseDonenessGaps("## Gaps\n- <unmet intent outcome>\n")).toEqual([]);
	});
	test("classifyDoneness: satisfied vs gap (not/absent/unparseable)", () => {
		expect(classifyDoneness(DONE("satisfied"))).toBe("satisfied");
		expect(classifyDoneness(DONE("not", ["a"]))).toBe("gap");
		expect(classifyDoneness(null)).toBe("gap");
		expect(classifyDoneness("garbage no verdict")).toBe("gap");
	});
	test("classifyDoneness: a template comment cannot satisfy the match", () => {
		expect(classifyDoneness("<!-- **Doneness:** satisfied -->\n**Doneness:** not\n")).toBe("gap");
	});

	test("ratchet: non-empty strict subset shrinks → progress + updates min", () => {
		expect(donenessRatchet(["a", "b"], ["a"])).toEqual({ progress: true, min: ["a"] });
	});
	test("ratchet: growth is not progress, min unchanged", () => {
		expect(donenessRatchet(["a"], ["a", "b"])).toEqual({ progress: false, min: ["a"] });
	});
	test("ratchet: equal-cardinality swap is not progress", () => {
		expect(donenessRatchet(["a", "b"], ["a", "c"])).toEqual({ progress: false, min: ["a", "b"] });
	});
	test("ratchet: asymmetric oscillation {a,b}→{a}→{a,b}→{a} cannot reset forever", () => {
		let m: string[] | undefined = ["a", "b"];
		let r = donenessRatchet(m, ["a"]); // shrink → progress
		expect(r.progress).toBe(true); m = r.min;
		r = donenessRatchet(m, ["a", "b"]); // up-swing → no progress
		expect(r.progress).toBe(false); m = r.min;
		r = donenessRatchet(m, ["a"]); // down-swing equals min, not a PROPER subset → no progress
		expect(r.progress).toBe(false);
		expect(r.min).toEqual(["a"]);
	});
	test("ratchet: empty-set sentinel is never progress and never overwrites min", () => {
		expect(donenessRatchet(["a", "b"], [])).toEqual({ progress: false, min: ["a", "b"] });
	});
	test("ratchet: first non-empty observation establishes the baseline (no progress)", () => {
		expect(donenessRatchet(undefined, ["a", "b"])).toEqual({ progress: false, min: ["a", "b"] });
	});
	test("ratchet: reword to same normalized membership is not progress", () => {
		expect(donenessRatchet(["a", "b"], ["a", "b"])).toEqual({ progress: false, min: ["a", "b"] });
	});
});

describe("verdictFromExit — opsx-loop-kickoff.opsx-gate-is-the-deterministic-judge", () => {
	test("exit 0 is met", () => {
		expect(verdictFromExit(0, "GATE-PASS: x (M)")).toEqual({ met: true, reason: "GATE-PASS: x (M)" });
	});
	test("exit 0 empty output still met", () => {
		expect(verdictFromExit(0, "  ")).toEqual({ met: true, reason: "opsx gate exited 0" });
	});
	test("non-zero is not met, report surfaced", () => {
		expect(verdictFromExit(1, "GATE-FAIL tasks 1 3 unchecked")).toEqual({
			met: false,
			reason: "GATE-FAIL tasks 1 3 unchecked",
		});
	});
	test("non-zero empty output reports code", () => {
		expect(verdictFromExit(2, "")).toEqual({ met: false, reason: "opsx gate exited 2" });
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
	test("undefined (unbounded) when absent", () => {
		expect(parseLoopBudget("---\nscale: M\n---\n")).toBeUndefined();
	});
	test("undefined (unbounded) when no front-matter", () => {
		expect(parseLoopBudget("# Review\nloop_max_iterations: 99\n")).toBeUndefined();
	});
	test("undefined (unbounded) on non-positive / non-numeric", () => {
		expect(parseLoopBudget(fm("0"))).toBeUndefined();
		expect(parseLoopBudget("---\nloop_max_iterations: abc\n---")).toBeUndefined();
	});
	test("undefined (unbounded) on empty input", () => {
		expect(parseLoopBudget("")).toBeUndefined();
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
	});
	test("change name containing a keyword is still a set", () => {
		expect(parseLoopArg("stop-the-flaky-tests")).toEqual({ mode: "set", change: "stop-the-flaky-tests" });
	});
	test("trailing tokens after a change name are surfaced as ignored, not truncated (argument-parsing-preserves-full-input)", () => {
		expect(parseLoopArg("  my-change  extra words ")).toEqual({ mode: "set", change: "my-change", ignored: "extra words" });
	});
	test("models routes with remaining tokens intact (model-config-subcommand)", () => {
		expect(parseLoopArg("models set author claude-bridge/claude-opus-4-8")).toEqual({
			mode: "models",
			args: ["set", "author", "claude-bridge/claude-opus-4-8"],
		});
		expect(parseLoopArg("models")).toEqual({ mode: "models", args: [] });
	});
	test("status/clear are leading keywords even with trailing tokens (argument-parsing-preserves-full-input)", () => {
		expect(parseLoopArg("status extra")).toEqual({ mode: "status" });
		expect(parseLoopArg("clear now")).toEqual({ mode: "clear" });
		expect(parseLoopArg("stop please")).toEqual({ mode: "clear" });
	});
});

describe("parseLoopArg goal keyword — opsx-loop-kickoff.goal-and-conversation-kickoff", () => {
	test("goal with multi-word text preserves the FULL goal (no truncation)", () => {
		expect(parseLoopArg("goal build the clipboard sync with retries")).toEqual({
			mode: "goal",
			goal: "build the clipboard sync with retries",
		});
	});
	test("goal with no following text starts from the conversation (goal omitted)", () => {
		expect(parseLoopArg("goal")).toEqual({ mode: "goal" });
		expect(parseLoopArg("  goal   ")).toEqual({ mode: "goal" });
	});
	test("goal is case-insensitive and collapses inner whitespace", () => {
		expect(parseLoopArg("GOAL   fix   the   thing")).toEqual({ mode: "goal", goal: "fix the thing" });
	});
	test("a change name that merely contains 'goal' is still a set", () => {
		expect(parseLoopArg("goal-tracker-extension")).toEqual({ mode: "set", change: "goal-tracker-extension" });
	});
});

describe("hashDir — opsx-loop-kickoff.stall-detection-stops-the-loop", () => {
	test("any file-content change under the dir changes the digest (incl. untracked)", () => {
		const root = mkdtempSync(join(tmpdir(), "opsxhash-"));
		const sub = join(root, "openspec", "changes", "c");
		mkdirSync(sub, { recursive: true });
		writeFileSync(join(sub, "tasks.md"), "- [ ] 1\n");
		const a = hashDir(sub);
		writeFileSync(join(sub, "tasks.md"), "- [x] 1\n"); // in-place edit (never git-added)
		const b = hashDir(sub);
		writeFileSync(join(sub, "new.md"), "fresh\n"); // brand-new untracked file
		const c = hashDir(sub);
		expect(a).not.toBe(b);
		expect(b).not.toBe(c);
	});
	test("identical content yields identical digest; missing dir is empty-safe", () => {
		const r1 = mkdtempSync(join(tmpdir(), "opsxhash-"));
		const r2 = mkdtempSync(join(tmpdir(), "opsxhash-"));
		writeFileSync(join(r1, "x.md"), "same\n");
		writeFileSync(join(r2, "x.md"), "same\n");
		expect(hashDir(r1)).toBe(hashDir(r2));
		expect(hashDir(join(r1, "does-not-exist"))).toBe(hashDir(join(r2, "does-not-exist")));
	});
});

describe("gateFailKey — opsx-loop-kickoff.stall-detection-stops-the-loop", () => {
	test("extracts the sorted set of GATE-FAIL check ids, excluding volatile text", () => {
		const report = [
			"GATE-FAIL tasks 1 unchecked tasks remain at /some/path abc123",
			"GATE-WARN advisory 0 ignored",
			"GATE-FAIL structure 1 openspec validate failed 2026-06-25T00:00",
		].join("\n");
		expect(gateFailKey(report)).toBe("structure,tasks");
	});
	test("identical check sets in different order produce the same key", () => {
		expect(gateFailKey("GATE-FAIL b 1 x\nGATE-FAIL a 1 y")).toBe(gateFailKey("GATE-FAIL a 1 z\nGATE-FAIL b 1 w"));
	});
	test("no GATE-FAIL lines yields empty key", () => {
		expect(gateFailKey("GATE-PASS: foo (L)")).toBe("");
	});
});

describe("buildModelEnv — opsx-loop-kickoff.loop-exports-resolved-role-models", () => {
	test("configured roles exported; unset roles omitted", () => {
		const env = buildModelEnv({
			author: { value: "claude-bridge/claude-opus-4-8", source: "project" },
			review: { value: ["a/x", "b/y"], source: "change" },
			impl: { value: null, source: "unset" },
			authorInSession: { value: true, source: "default" },
		});
		expect(env.OPSX_AUTHOR_MODEL).toBe("claude-bridge/claude-opus-4-8");
		expect(env.OPSX_REVIEW_MODELS).toBe("a/x\nb/y");
		expect("OPSX_IMPL_MODEL" in env).toBe(false);
		expect(env.OPSX_AUTHOR_IN_SESSION).toBe("true");
	});
	test("default-source roles are treated as unconfigured (omitted)", () => {
		const env = buildModelEnv({ author: { value: "session", source: "default" } });
		expect("OPSX_AUTHOR_MODEL" in env).toBe(false);
	});
	test("author_in_session false exported as string", () => {
		const env = buildModelEnv({ authorInSession: { value: false, source: "change" } });
		expect(env.OPSX_AUTHOR_IN_SESSION).toBe("false");
	});
	test("single-string review still exported", () => {
		const env = buildModelEnv({ review: { value: "only/one", source: "user" } });
		expect(env.OPSX_REVIEW_MODELS).toBe("only/one");
	});
});

describe("parseModelsJson — opsx-loop-kickoff.loop-exports-resolved-role-models", () => {
	test("parses well-formed source-aware json", () => {
		expect(parseModelsJson('{"value":"x/y","source":"env"}')).toEqual({ value: "x/y", source: "env" });
	});
	test("null on malformed input", () => {
		expect(parseModelsJson("not json")).toBeNull();
		expect(parseModelsJson("")).toBeNull();
		expect(parseModelsJson('{"value":"x"}')).toBeNull();
	});
});
