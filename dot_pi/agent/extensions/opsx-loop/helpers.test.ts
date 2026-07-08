// Unit tests for opsx-loop pure helpers.
// Acceptance criteria cited by canonical ID for the opsx verify gate:
//   opsx-loop.opsx-gate-is-the-deterministic-judge
//   opsx-loop.budget-from-review-front-matter
//   opsx-loop.status-and-clear-subcommands
import { describe, expect, test } from "bun:test";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { buildModelEnv, classifyDoneness, clearHoldText, describeCompactPolicy, donenessRatchet, formatInventory, gateFailKey, hashDir, isContextOverflowError, listIntentChanges, OPSX_MODEL_ENV_KEYS, parseDonenessGaps, parseLoopArg, parseLoopBudget, parseLoopHold, parseModelsJson, resolveCompactPercent, resolveCompactThresholdTokens, resolveCompactTokens, stripLoopHold, verdictFromExit, ELIDE_STUB, resolveElideKeepPercent, resolveElideBandPercent, resolveElideMaxKeepTokens, resolveElideBandTokens, estimateMessageTokens, tokenBudgetBoundary, elideToolResultBodies } from "./helpers.ts";

type TR = { role: string; content: unknown; toolCallId?: string; toolName?: string };
const asst = (id: string) => ({ role: "assistant", content: [{ type: "text", text: "call" }, { type: "toolCall", id, name: "bash", arguments: {} }] });
const tr = (id: string, text: string) => ({ role: "toolResult", toolCallId: id, toolName: "bash", isError: false, content: [{ type: "text", text }] });
// Build a conversation of N assistant+toolResult turns (turn k => assistant#k, tr#k).
function convo(n: number) {
	const msgs: any[] = [{ role: "user", content: "go" }];
	for (let k = 0; k < n; k++) {
		msgs.push(asst(`c${k}`));
		msgs.push(tr(`c${k}`, `OUTPUT-${k}`));
	}
	return msgs;
}

describe("parseLoopHold / stripLoopHold — opsx-loop.loop-hold-blocks-continuation", () => {
	const FM = (body: string) => `---\n${body}\n---\n# Review\n`;
	test("loop_hold: true with reason → held", () => {
		const h = parseLoopHold(FM('scale: M\nloop_hold: true\nloop_hold_reason: "decision audit pending"'));
		expect(h.held).toBe(true);
		expect(h.reason).toBe("decision audit pending");
	});
	test("hold honored even with empty reason (fail-safe, clarify C1)", () => {
		expect(parseLoopHold(FM("loop_hold: true")).held).toBe(true);
		expect(parseLoopHold(FM("loop_hold: true")).reason).toBe("");
	});
	test("absent / false / malformed / outside-front-matter → not held", () => {
		expect(parseLoopHold(FM("scale: M")).held).toBe(false);
		expect(parseLoopHold(FM("loop_hold: false")).held).toBe(false);
		expect(parseLoopHold(FM('loop_hold: "true" junk')).held).toBe(false);
		expect(parseLoopHold("# Review\nloop_hold: true\n").held).toBe(false);
	});
	test("stripLoopHold removes only the hold fields, keeps everything else", () => {
		const md = FM('scale: M\nloop_hold: true\nloop_hold_reason: "why"\ndoneness_mode: required');
		const out = stripLoopHold(md);
		expect(out).toContain("scale: M");
		expect(out).toContain("doneness_mode: required");
		expect(out).not.toContain("loop_hold");
		expect(parseLoopHold(out).held).toBe(false);
	});
	test("stripLoopHold is a no-op without hold fields (and never touches the body)", () => {
		const md = FM("scale: M") + "body loop_hold: true mention\n";
		expect(stripLoopHold(md)).toBe(md);
	});
	test("clearHoldText strips the hold AND appends the auditable Execution Notes line", () => {
		const md = FM('scale: M\nloop_hold: true\nloop_hold_reason: "audit pending"') + "\n## Execution Notes\n\n- old note\n";
		const { next, reason } = clearHoldText(md, "my-change", "2026-07-03");
		expect(reason).toBe("audit pending");
		expect(parseLoopHold(next).held).toBe(false);
		expect(next).toContain("- 2026-07-03 — loop_hold cleared by named re-arm (/opsx-loop my-change); reason was: audit pending");
		expect(next).toContain("- old note");
	});
	test("clearHoldText creates Execution Notes when absent; empty reason recorded as such", () => {
		const { next } = clearHoldText(FM("loop_hold: true"), "c", "2026-07-03");
		expect(next).toContain("## Execution Notes");
		expect(next).toContain("reason was: (none recorded)");
	});
	test("clearHoldText survives $-replacement patterns in the reason", () => {
		const md = FM("loop_hold: true\nloop_hold_reason: \"costs $& and $' extra\"") + "\n## Execution Notes\n";
		const { next } = clearHoldText(md, "c", "2026-07-03");
		expect(next).toContain("costs $& and $' extra");
	});
	test("clearHoldText anchors to the exact heading line, not a longer heading", () => {
		const md = FM("loop_hold: true") + "\n## Execution Notes (archived)\n\n## Execution Notes\n";
		const { next } = clearHoldText(md, "c", "2026-07-03");
		expect(next.indexOf("loop_hold cleared")).toBeGreaterThan(next.indexOf("## Execution Notes (archived)"));
	});
	test("parseLoopHold accepts YAML-canonical True (case-insensitive boolean)", () => {
		expect(parseLoopHold(FM("loop_hold: True")).held).toBe(true);
	});
});

describe("active-change inventory — opsx-loop.goal-and-conversation-kickoff", () => {
	const mkRepo = () => {
		const d = mkdtempSync(join(tmpdir(), "opsx-inv-"));
		const ch = (name: string, files: Record<string, string>) => {
			mkdirSync(join(d, "openspec", "changes", name), { recursive: true });
			for (const [f, c] of Object.entries(files)) writeFileSync(join(d, "openspec", "changes", name, f), c);
		};
		return { d, ch };
	};
	test("lists only intent.md-bearing changes with cheap front-matter scale, sorted", () => {
		const { d, ch } = mkRepo();
		ch("zeta", { "intent.md": "# I", "review.md": "---\nscale: M\n---\n" });
		ch("alpha", { "intent.md": "# I" }); // no review.md → scale "?"
		ch("no-intent", { "review.md": "---\nscale: S\n---\n" });
		expect(listIntentChanges(d)).toEqual([
			{ name: "alpha", scale: "?" },
			{ name: "zeta", scale: "M" },
		]);
	});
	test("archive excluded; missing changes dir → empty; no gate runs or model calls by construction", () => {
		const { d, ch } = mkRepo();
		mkdirSync(join(d, "openspec", "changes", "archive", "old"), { recursive: true });
		writeFileSync(join(d, "openspec", "changes", "archive", "intent.md"), "x");
		expect(listIntentChanges(d)).toEqual([]);
		expect(listIntentChanges(join(d, "nowhere"))).toEqual([]);
		ch;
	});
	test("formatInventory renders directive lines; empty → (none)", () => {
		expect(formatInventory([])).toBe("(none)");
		expect(formatInventory([{ name: "a", scale: "M" }])).toBe("  - a (scale: M)");
	});
	test("committed predicate excludes working-tree-only intent drafts", () => {
		const { d, ch } = mkRepo();
		ch("tracked", { "intent.md": "# I" });
		ch("draft-only", { "intent.md": "# I" });
		expect(listIntentChanges(d, (n) => n === "tracked")).toEqual([{ name: "tracked", scale: "?" }]);
	});
});

describe("doneness stall helpers — opsx-loop.stall-detection-stops-the-loop", () => {
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

describe("verdictFromExit — opsx-loop.opsx-gate-is-the-deterministic-judge", () => {
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

describe("parseLoopBudget — opsx-loop.budget-from-review-front-matter", () => {
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
		// STRICT whole-value parse: garbage prefix/suffix, negatives, and quoted
		// values are unparseable => unset, never a silently mangled number.
		expect(parseLoopBudget(fm("80junk"))).toBeUndefined();
		expect(parseLoopBudget(fm("abc80"))).toBeUndefined();
		expect(parseLoopBudget(fm("-1"))).toBeUndefined();
		expect(parseLoopBudget(fm('"80"'))).toBeUndefined();
		expect(parseLoopBudget(fm("80 "))).toBe(80);
	});
	test("undefined (unbounded) on empty input", () => {
		expect(parseLoopBudget("")).toBeUndefined();
	});
});

describe("compaction threshold resolution — opsx-loop proactive compaction (Lever A, default-on)", () => {
	test("percent term: default 33 when unset/garbage; explicit value; OFF -> null", () => {
		expect(resolveCompactPercent(undefined)).toBe(33);
		expect(resolveCompactPercent("")).toBe(33);
		expect(resolveCompactPercent("abc")).toBe(33); // garbage falls back to default, never disables
		expect(resolveCompactPercent("150")).toBe(33); // out of range -> default
		expect(resolveCompactPercent("50")).toBe(50);
		expect(resolveCompactPercent(" 40 ")).toBe(40);
		for (const off of ["off", "none", "false", "0", "OFF"]) expect(resolveCompactPercent(off)).toBeNull();
	});
	test("token term: default 100000 when unset/garbage; explicit value; OFF -> null", () => {
		expect(resolveCompactTokens(undefined)).toBe(100_000);
		expect(resolveCompactTokens("garbage")).toBe(100_000);
		expect(resolveCompactTokens("250000")).toBe(250_000);
		for (const off of ["off", "none", "0"]) expect(resolveCompactTokens(off)).toBeNull();
	});
	test("threshold = max(pct*window, tokenFloor) — 'whichever higher'", () => {
		// 200k window, defaults: max(33% * 200k = 66k, 100k) = 100k
		expect(resolveCompactThresholdTokens(200_000, undefined, undefined)).toBe(100_000);
		// 1M window, defaults: max(330k, 100k) = 330k
		expect(resolveCompactThresholdTokens(1_000_000, undefined, undefined)).toBe(330_000);
		// explicit percent dominates when higher
		expect(resolveCompactThresholdTokens(1_000_000, "50", "100000")).toBe(500_000);
	});
	test("either term OFF uses the other; BOTH off => disabled (undefined)", () => {
		expect(resolveCompactThresholdTokens(200_000, "off", undefined)).toBe(100_000); // floor only
		expect(resolveCompactThresholdTokens(200_000, undefined, "off")).toBe(66_000); // ceil(33% * 200k)
		expect(resolveCompactThresholdTokens(200_000, "off", "off")).toBeUndefined();
	});
	test("non-positive window drops the percent term", () => {
		expect(resolveCompactThresholdTokens(0, undefined, undefined)).toBe(100_000); // floor survives
		expect(resolveCompactThresholdTokens(0, undefined, "off")).toBeUndefined(); // nothing left
	});
	test("describeCompactPolicy reflects on/off state", () => {
		expect(describeCompactPolicy(undefined, undefined)).toMatch(/33% window or 100,000 tokens/);
		expect(describeCompactPolicy("off", "off")).toBe("compaction guard: off");
		expect(describeCompactPolicy("off", undefined)).toMatch(/100,000 tokens/);
	});
});

describe("isContextOverflowError — opsx-loop overflow-only recovery", () => {
	test("error-message overflow patterns across providers", () => {
		const m = (errorMessage: string) => ({ stopReason: "error", errorMessage });
		expect(isContextOverflowError(m("prompt is too long: 213462 tokens > 200000 maximum"))).toBe(true);
		expect(isContextOverflowError(m("Your input exceeds the context window of this model"))).toBe(true);
		expect(isContextOverflowError(m("Requested token count exceeds the model's maximum context length of 131072 tokens"))).toBe(true);
		expect(isContextOverflowError(m("This model's maximum prompt length is 131072 but the request contains 537812 tokens"))).toBe(true);
		expect(isContextOverflowError(m("context_length_exceeded"))).toBe(true);
	});
	test("rate-limit / throttle errors are NOT overflow (non-overflow guard wins)", () => {
		// pi reformats Bedrock throttles to a "Throttling error:" prefix before this check
		expect(isContextOverflowError({ stopReason: "error", errorMessage: "Throttling error: Too many tokens, please wait" })).toBe(false);
		expect(isContextOverflowError({ stopReason: "error", errorMessage: "429 rate limit exceeded" })).toBe(false);
	});
	test("non-overflow errors and clean stops are false", () => {
		expect(isContextOverflowError({ stopReason: "error", errorMessage: "connection reset by peer" })).toBe(false);
		expect(isContextOverflowError({ stopReason: "error" })).toBe(false); // no errorMessage
		expect(isContextOverflowError({ stopReason: "stop", usage: { input: 10, cacheRead: 0, output: 5 } }, 200000)).toBe(false);
		expect(isContextOverflowError(undefined)).toBe(false);
	});
	test("silent overflow: stop with input+cacheRead over the window", () => {
		expect(isContextOverflowError({ stopReason: "stop", usage: { input: 190000, cacheRead: 20000, output: 100 } }, 200000)).toBe(true);
		expect(isContextOverflowError({ stopReason: "stop", usage: { input: 150000, cacheRead: 20000, output: 100 } }, 200000)).toBe(false);
		// without a window, silent overflow cannot be detected
		expect(isContextOverflowError({ stopReason: "stop", usage: { input: 300000, cacheRead: 0, output: 1 } })).toBe(false);
	});
	test("length-stop overflow: zero output + input filling >=99% of window", () => {
		expect(isContextOverflowError({ stopReason: "length", usage: { input: 199000, cacheRead: 500, output: 0 } }, 200000)).toBe(true);
		expect(isContextOverflowError({ stopReason: "length", usage: { input: 199000, cacheRead: 500, output: 42 } }, 200000)).toBe(false);
	});
});

describe("parseLoopArg — opsx-loop.status-and-clear-subcommands", () => {
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

describe("parseLoopArg goal keyword — opsx-loop.goal-and-conversation-kickoff", () => {
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

describe("hashDir — opsx-loop.stall-detection-stops-the-loop", () => {
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

describe("gateFailKey — opsx-loop.stall-detection-stops-the-loop", () => {
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

describe("buildModelEnv — opsx-loop.loop-exports-resolved-role-models", () => {
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
	test("every exportable key is covered by OPSX_MODEL_ENV_KEYS (leak-proof clear list)", () => {
		// The extension deletes OPSX_MODEL_ENV_KEYS from process.env before each
		// export; if buildModelEnv ever grows a key missing from that list, stale
		// values would leak across sequential loops. Keep the two in lockstep.
		const env = buildModelEnv({
			author: { value: "a/m", source: "change" },
			review: { value: ["a/m", "b/n"], source: "project" },
			impl: { value: "c/o", source: "user" },
			authorInSession: { value: false, source: "change" },
		});
		for (const k of Object.keys(env)) {
			expect(OPSX_MODEL_ENV_KEYS as readonly string[]).toContain(k);
		}
		expect(Object.keys(env).length).toBe(OPSX_MODEL_ENV_KEYS.length);
	});
	test("single-string review still exported", () => {
		const env = buildModelEnv({ review: { value: "only/one", source: "user" } });
		expect(env.OPSX_REVIEW_MODELS).toBe("only/one");
	});
});

describe("parseModelsJson — opsx-loop.loop-exports-resolved-role-models", () => {
	test("parses well-formed source-aware json", () => {
		expect(parseModelsJson('{"value":"x/y","source":"env"}')).toEqual({ value: "x/y", source: "env" });
	});
	test("null on malformed input", () => {
		expect(parseModelsJson("not json")).toBeNull();
		expect(parseModelsJson("")).toBeNull();
		expect(parseModelsJson('{"value":"x"}')).toBeNull();
	});
});

// AC opsx-loop-context-elision.threshold-band-gating

// AC opsx-loop-context-elision.token-budget-boundary,
//    opsx-loop-context-elision.token-band-hysteresis
describe("token-budget elision resolvers", () => {
	test("keep/band percent defaults", () => {
		expect(resolveElideKeepPercent(undefined)).toBe(40);
		expect(resolveElideBandPercent(undefined)).toBe(5);
	});
	test("garbage / out-of-range → default", () => {
		expect(resolveElideKeepPercent("abc")).toBe(40);
		expect(resolveElideKeepPercent("0")).toBe(40);
		expect(resolveElideKeepPercent("150")).toBe(40);
		expect(resolveElideBandPercent("xx")).toBe(5);
		expect(resolveElideBandPercent("0")).toBe(5);
	});
	test("explicit overrides honored", () => {
		expect(resolveElideKeepPercent("50")).toBe(50);
		expect(resolveElideBandPercent("10")).toBe(10);
	});
	test("maxKeep / band tokens = percent-of-window, no absolute floor", () => {
		expect(resolveElideMaxKeepTokens(272_000, undefined)).toBe(108_800); // 40% × 272k
		expect(resolveElideMaxKeepTokens(200_000, "50")).toBe(100_000);
		expect(resolveElideBandTokens(272_000, undefined)).toBe(13_600); // 5% × 272k
	});
	test("unknown/non-positive window → undefined (caller degrades)", () => {
		expect(resolveElideMaxKeepTokens(0, undefined)).toBeUndefined();
		expect(resolveElideMaxKeepTokens(Number.NaN, undefined)).toBeUndefined();
		expect(resolveElideBandTokens(0, undefined)).toBeUndefined();
	});
	test("budget scales with window on any size (dynamic, no floor)", () => {
		for (const w of [128_000, 200_000, 400_000, 1_000_000]) {
			expect(resolveElideMaxKeepTokens(w, undefined)).toBe(Math.ceil(0.4 * w));
			expect(resolveElideBandTokens(w, undefined)).toBe(Math.ceil(0.05 * w));
		}
	});
});

// AC opsx-loop-context-elision.deterministic-no-model-call (char/4 estimate)
describe("estimateMessageTokens — deterministic char/4", () => {
	test("string content, text blocks, tool-call name+args, thinking", () => {
		expect(estimateMessageTokens({ role: "user", content: "go" })).toBe(1); // 2 chars
		expect(estimateMessageTokens(tr("c0", "OUTPUT-0"))).toBe(2); // "OUTPUT-0" = 8 chars
		expect(estimateMessageTokens(asst("c0"))).toBe(3); // "call"+"bash"+"{}" = 10 chars
		expect(
			estimateMessageTokens({ role: "assistant", content: [{ type: "thinking", thinking: "xxxxxxxx" }] }),
		).toBe(2); // 8 chars
		expect(estimateMessageTokens({ role: "assistant", content: [{ type: "image" }] })).toBe(0);
	});
});

// AC opsx-loop-context-elision.token-budget-boundary,
//    opsx-loop-context-elision.token-band-hysteresis
// Uniform 1-token turns (each a minimal assistant msg, estimate = ceil(1/4) = 1),
// used to exercise band-quantized hysteresis deterministically.
const uni = (n: number) => Array.from({ length: n }, () => ({ role: "assistant", content: [{ type: "text", text: "x" }] }));
// Turns of EXACT token estimates: one assistant msg per entry, text length = tok*4 so
// estimateMessageTokens = ceil(tok*4/4) = tok. Lets tests place a chunky NON-oldest turn.
const sizedTurns = (toks: number[]) =>
	toks.map((tk) => ({ role: "assistant", content: [{ type: "text", text: "y".repeat(Math.max(1, tk) * 4) }] }));
const keptSum = (toks: number[], boundary: number) => toks.slice(boundary).reduce((a, x) => a + x, 0);
describe("tokenBudgetBoundary", () => {
	// convo(20): perTurn = [6, 5×9, 6×10] (turn0 carries the leading user msg;
	// OUTPUT-10..19 are 9 chars → 3 tok each), total = 111. Sheds oldest turns until the
	// shed prefix reaches the band-quantized shed floor ceil((total-ceiling)/band)*band.
	test("snaps boundary to a turn edge (banded shed floor of the oldest turns)", () => {
		// maxKeep=25, band=5 → ceiling=30 → shedFloor=81 → bandedShedFloor=85 → boundary 16.
		expect(tokenBudgetBoundary(convo(20), 25, 5)).toBe(16);
	});
	test("band hysteresis — boundary STABLE within a band, advances across it", () => {
		// 1-tok turns, maxKeep=10, band=5 → ceiling=15. total 21..25 share bandedShedFloor=10
		// → boundary byte-stable at 10 (prompt-cache friendly); at total=26 the band edge is
		// crossed (bandedShedFloor=15) and the boundary advances to 15.
		expect(tokenBudgetBoundary(uni(21), 10, 5)).toBe(10);
		expect(tokenBudgetBoundary(uni(24), 10, 5)).toBe(10);
		expect(tokenBudgetBoundary(uni(25), 10, 5)).toBe(10);
		expect(tokenBudgetBoundary(uni(26), 10, 5)).toBe(15);
	});
	test("kept-full window ≤ ceiling with a chunky NON-oldest turn (non-tautological)", () => {
		// A big stale turn (110) sits AFTER a small oldest turn (3). ceiling = 100+10 = 110.
		// The boundary MUST shed the 110 turn so the kept window stays ≤ ceiling.
		const b = tokenBudgetBoundary(sizedTurns([3, 110, 3]), 100, 10);
		expect(b).toBe(2); // turns 0 (3) and 1 (110) shed; kept = newest turn (3)
		expect(keptSum([3, 110, 3], b)).toBeLessThanOrEqual(110);
		// A chunky middle turn among several: ceiling = 100+5 = 105.
		const c = tokenBudgetBoundary(sizedTurns([40, 40, 40, 40, 10]), 100, 5);
		expect(keptSum([40, 40, 40, 40, 10], c)).toBeLessThanOrEqual(105);
	});
	test("fires and elides a large OLD turn (regression: no fire-but-noop)", () => {
		// Two turns: an old turn ~54 tok (big tool result) and a newest ~39 tok.
		// maxKeep=40, band=10 → ceiling=50; total=93 > 50 so elision MUST fire and shed the
		// old turn even though it exceeds the shed floor — boundary 1, keeping the newest.
		const g: any[] = [asst("a0"), tr("a0", "X".repeat(204)), asst("a1"), tr("a1", "X".repeat(144))];
		expect(tokenBudgetBoundary(g, 40, 10)).toBe(1);
	});
	test("within budget + band → hysteresis hold (no elision)", () => {
		// total=111; ceiling = 107+5 = 112 > 111 → hold → boundary 0.
		expect(tokenBudgetBoundary(convo(20), 107, 5)).toBe(0);
		// far under budget → 0.
		expect(tokenBudgetBoundary(convo(20), 1_000_000, 5)).toBe(0);
	});
	test("newest turn always kept even when it alone exceeds the budget", () => {
		const b = tokenBudgetBoundary(convo(20), 1, 1); // tiny budget
		expect(b).toBeLessThan(20); // boundary never reaches totalTurns → newest turn survives
		expect(b).toBe(19); // everything before the newest turn sheds
	});
	test("single turn / empty → no elision", () => {
		expect(tokenBudgetBoundary(convo(1), 1, 1)).toBe(0);
		expect(tokenBudgetBoundary([] as any, 25, 5)).toBe(0);
	});
});

// ACs opsx-loop-context-elision.stale-tool-result-body-elision,
//     opsx-loop-context-elision.structural-integrity-fail-closed,
//     opsx-loop-context-elision.no-history-mutation,
//     opsx-loop-context-elision.token-budget-boundary
describe("elideToolResultBodies (token-budget boundary)", () => {
	test("old tool-result bodies → stub, kept-full recent window preserved", () => {
		const msgs = convo(20); // boundary=16 with maxKeep=25, band=5
		const before = JSON.parse(JSON.stringify(msgs));
		const { messages: out, elided } = elideToolResultBodies(msgs, { maxKeepTokens: 25, bandTokens: 5 });
		expect(elided).toBe(true);
		expect(out.length).toBe(msgs.length);
		const trOut = out.filter((m: any) => m.role === "toolResult");
		expect(trOut.length).toBe(20); // pairing preserved (every toolResult still present)
		// turn 0 (old) elided
		const t0 = trOut[0] as any;
		expect(t0.toolCallId).toBe("c0");
		expect(t0.content[0].text).toBe(ELIDE_STUB);
		// turn 15 (last elided) → stub; turn 16 (first kept) → full
		expect((trOut[15] as any).content[0].text).toBe(ELIDE_STUB);
		expect((trOut[16] as any).content[0].text).toBe("OUTPUT-16");
		// newest turn (19) preserved
		expect((trOut[19] as any).content[0].text).toBe("OUTPUT-19");
		// INPUT NOT MUTATED
		expect(msgs).toEqual(before);
	});
	test("non-tool-result content untouched", () => {
		const msgs = convo(20);
		const { messages: out } = elideToolResultBodies(msgs, { maxKeepTokens: 25, bandTokens: 5 });
		const a0 = out.find((m: any) => m.role === "assistant") as any;
		expect(a0.content[1].id).toBe("c0");
		expect((out[0] as any).role).toBe("user");
	});
	test("within budget → no elision (pass-through)", () => {
		const msgs = convo(20);
		const { messages: out, elided } = elideToolResultBodies(msgs, { maxKeepTokens: 1_000_000, bandTokens: 5 });
		expect(elided).toBe(false);
		expect(out).toBe(msgs);
	});
	test("idempotent — already-stubbed results do not re-fire elided flag", () => {
		const msgs = convo(20);
		const first = elideToolResultBodies(msgs, { maxKeepTokens: 25, bandTokens: 5 });
		const second = elideToolResultBodies(first.messages, { maxKeepTokens: 25, bandTokens: 5 });
		expect(second.elided).toBe(false);
	});
	test("fail-closed on malformed input", () => {
		expect(elideToolResultBodies(null as any).elided).toBe(false);
		expect(elideToolResultBodies([] as any).elided).toBe(false);
		const weird = [{ role: "toolResult", content: "not-an-array" }] as any;
		expect(elideToolResultBodies(weird).elided).toBe(false);
	});
	test("fail-closed when an OLD tool-result has malformed (non-array) content amid valid siblings", () => {
		const msgs = convo(20) as any[];
		const firstTr = msgs.findIndex((m) => m.role === "toolResult");
		msgs[firstTr] = { ...msgs[firstTr], content: "not-an-array" };
		const before = JSON.parse(JSON.stringify(msgs));
		const { messages: out, elided } = elideToolResultBodies(msgs, { maxKeepTokens: 25, bandTokens: 5 });
		expect(elided).toBe(false);
		expect(out).toBe(msgs);
		expect(msgs).toEqual(before);
	});
	test("fail-closed when an OLD tool-result is orphaned (no matching tool_call)", () => {
		const msgs = convo(20) as any[];
		const firstTr = msgs.findIndex((m) => m.role === "toolResult");
		msgs[firstTr] = { ...msgs[firstTr], toolCallId: "ORPHAN-does-not-exist" };
		const { messages: out, elided } = elideToolResultBodies(msgs, { maxKeepTokens: 25, bandTokens: 5 });
		expect(elided).toBe(false);
		expect(out).toBe(msgs);
	});
});
