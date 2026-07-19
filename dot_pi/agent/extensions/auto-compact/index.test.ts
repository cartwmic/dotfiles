import { describe, expect, test } from "bun:test";
import extension from "./index.ts";
import {
	DEFAULT_CONFIG,
	describeConfig,
	normalizeConfig,
	shouldTrigger,
	thresholdTokens,
} from "./config.ts";

describe("auto-compact config", () => {
	test("defaults to enabled, 40%, and both check points", () => {
		expect(normalizeConfig(undefined)).toEqual(DEFAULT_CONFIG);
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

	test("describes effective configuration", () => {
		expect(describeConfig(DEFAULT_CONFIG)).toBe(
			"auto-compaction ON; threshold 40%; check at turn_end + agent_end",
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
		extension({
			on: (name: string, handler: (event: unknown, ctx: any) => void) => handlers.set(name, handler),
			registerCommand: (name: string) => commands.push(name),
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
	});
});
