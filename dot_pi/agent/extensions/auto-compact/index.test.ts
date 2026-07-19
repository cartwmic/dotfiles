import { describe, expect, test } from "bun:test";
import extension from "./index.ts";
import {
	DEFAULT_CONFIG,
	DEFAULT_CONTINUATION,
	describeConfig,
	normalizeConfig,
	normalizeContinuation,
	resumeAfterCompact,
	shouldTrigger,
	thresholdTokens,
} from "./config.ts";

describe("auto-compact config", () => {
	test("defaults to enabled, 40%, both check points, and continuation on", () => {
		expect(normalizeConfig(undefined)).toEqual(DEFAULT_CONFIG);
		expect(DEFAULT_CONFIG.continuation).toBe(DEFAULT_CONTINUATION);
	});

	test("accepts one or both supported check points", () => {
		expect(normalizeConfig({ checkAt: ["agent_end"] }).checkAt).toEqual(["agent_end"]);
		expect(normalizeConfig({ checkAt: ["agent_end", "turn_end"] }).checkAt).toEqual([
			"turn_end",
			"agent_end",
		]);
	});

	test("falls back safely for invalid thresholds and check points", () => {
		expect(normalizeConfig({ thresholdPercent: 0, checkAt: ["message_end"] })).toEqual(DEFAULT_CONFIG);
		expect(normalizeConfig({ thresholdPercent: 101 }).thresholdPercent).toBe(40);
	});

	test("normalizes continuation (default, custom, false, empty)", () => {
		expect(normalizeContinuation(undefined)).toBe(DEFAULT_CONTINUATION);
		expect(normalizeContinuation("Keep going.")).toBe("Keep going.");
		expect(normalizeContinuation(false)).toBe(false);
		expect(normalizeContinuation("   ")).toBe(false);
		expect(normalizeConfig({}).continuation).toBe(DEFAULT_CONTINUATION);
		expect(normalizeConfig({ continuation: false }).continuation).toBe(false);
		expect(normalizeConfig({ continuation: " Resume. " }).continuation).toBe("Resume.");
	});

	test("describes effective configuration", () => {
		expect(describeConfig(DEFAULT_CONFIG)).toBe(
			`auto-compaction ON; threshold 40%; check at turn_end + agent_end; continuation "${DEFAULT_CONTINUATION}"`,
		);
		expect(describeConfig({ ...DEFAULT_CONFIG, continuation: false })).toContain("continuation OFF");
	});

	test("resumes only after mid-turn compaction when continuation is enabled", () => {
		expect(resumeAfterCompact(DEFAULT_CONFIG, "turn_end")).toBe(DEFAULT_CONTINUATION);
		expect(resumeAfterCompact(DEFAULT_CONFIG, "agent_end")).toBeUndefined();
		expect(resumeAfterCompact({ ...DEFAULT_CONFIG, continuation: false }, "turn_end")).toBeUndefined();
		expect(resumeAfterCompact({ ...DEFAULT_CONFIG, continuation: "Keep going." }, "turn_end")).toBe(
			"Keep going.",
		);
	});
});

describe("auto-compact threshold", () => {
	test("calculates a dynamic percentage of each model window", () => {
		expect(thresholdTokens(372_000, 40)).toBe(148_800);
		expect(thresholdTokens(200_001, 40)).toBe(80_001);
	});

	test("triggers inclusively at the threshold", () => {
		const usage = { tokens: 148_800, contextWindow: 372_000 };
		expect(shouldTrigger(DEFAULT_CONFIG, "turn_end", usage)).toBe(true);
		expect(shouldTrigger(DEFAULT_CONFIG, "agent_end", usage)).toBe(true);
	});

	test("respects selected check points", () => {
		const config = normalizeConfig({ checkAt: ["agent_end"] });
		const usage = { tokens: 148_800, contextWindow: 372_000 };
		expect(shouldTrigger(config, "turn_end", usage)).toBe(false);
		expect(shouldTrigger(config, "agent_end", usage)).toBe(true);
	});

	test("does not repeat at the same token count after an attempt", () => {
		const usage = { tokens: 150_000, contextWindow: 372_000 };
		expect(shouldTrigger(DEFAULT_CONFIG, "agent_end", usage, 150_000)).toBe(false);
		expect(shouldTrigger(DEFAULT_CONFIG, "agent_end", { ...usage, tokens: 150_001 }, 150_000)).toBe(true);
	});

	test("does not trigger below threshold or while disabled", () => {
		expect(
			shouldTrigger(DEFAULT_CONFIG, "turn_end", { tokens: 148_799, contextWindow: 372_000 }),
		).toBe(false);
		expect(
			shouldTrigger(
				{ ...DEFAULT_CONFIG, enabled: false },
				"turn_end",
				{ tokens: 148_800, contextWindow: 372_000 },
			),
		).toBe(false);
	});

	test("checks both event levels but compacts once at the same usage", () => {
		const handlers = new Map<string, (event: unknown, ctx: any) => void>();
		const commands: string[] = [];
		const followUps: Array<{ text: string; options?: { deliverAs?: string } }> = [];
		extension({
			on: (name: string, handler: (event: unknown, ctx: any) => void) => handlers.set(name, handler),
			registerCommand: (name: string) => commands.push(name),
			sendUserMessage: (text: string, options?: { deliverAs?: string }) => {
				followUps.push({ text, options });
			},
		} as any);

		let compactCalls = 0;
		const ctx = {
			hasUI: false,
			getContextUsage: () => ({ tokens: 148_800, contextWindow: 372_000 }),
			compact: ({ onComplete }: { onComplete: () => void }) => {
				compactCalls += 1;
				onComplete();
			},
		};
		handlers.get("turn_end")?.({}, ctx);
		handlers.get("agent_end")?.({}, ctx);

		expect(compactCalls).toBe(1);
		expect(commands).toContain("auto-compact");
		expect(followUps).toEqual([{ text: DEFAULT_CONTINUATION, options: { deliverAs: "followUp" } }]);
	});

	test("does not resume after agent_end compaction", () => {
		const handlers = new Map<string, (event: unknown, ctx: any) => void>();
		const followUps: string[] = [];
		extension({
			on: (name: string, handler: (event: unknown, ctx: any) => void) => handlers.set(name, handler),
			registerCommand: () => {},
			sendUserMessage: (text: string) => {
				followUps.push(text);
			},
		} as any);

		const ctx = {
			hasUI: false,
			getContextUsage: () => ({ tokens: 148_800, contextWindow: 372_000 }),
			compact: ({ onComplete }: { onComplete: () => void }) => {
				onComplete();
			},
		};
		handlers.get("agent_end")?.({}, ctx);
		expect(followUps).toEqual([]);
	});

	test("resumes on compact error after mid-turn abort", () => {
		const handlers = new Map<string, (event: unknown, ctx: any) => void>();
		const followUps: string[] = [];
		extension({
			on: (name: string, handler: (event: unknown, ctx: any) => void) => handlers.set(name, handler),
			registerCommand: () => {},
			sendUserMessage: (text: string) => {
				followUps.push(text);
			},
		} as any);

		const ctx = {
			hasUI: false,
			getContextUsage: () => ({ tokens: 148_800, contextWindow: 372_000 }),
			compact: ({ onError }: { onError: (error: Error) => void }) => {
				onError(new Error("Nothing to compact (session too small)"));
			},
		};
		handlers.get("turn_end")?.({}, ctx);
		expect(followUps).toEqual([DEFAULT_CONTINUATION]);
	});
});
