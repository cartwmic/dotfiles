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
			`auto-compaction ON; threshold 40%; check at turn_end + agent_end; continuation "${DEFAULT_CONTINUATION}"; breaker 2`,
		);
		expect(describeConfig({ ...DEFAULT_CONFIG, continuation: false })).toContain("continuation OFF");
	});

	test("normalizes the circuit-breaker limit (default, floor, invalid)", () => {
		expect(normalizeConfig(undefined).maxIneffectiveCompactions).toBe(2);
		expect(normalizeConfig({ maxIneffectiveCompactions: 5 }).maxIneffectiveCompactions).toBe(5);
		expect(normalizeConfig({ maxIneffectiveCompactions: 3.7 }).maxIneffectiveCompactions).toBe(3);
		expect(normalizeConfig({ maxIneffectiveCompactions: 0 }).maxIneffectiveCompactions).toBe(2);
		expect(normalizeConfig({ maxIneffectiveCompactions: -4 }).maxIneffectiveCompactions).toBe(2);
		expect(normalizeConfig({ maxIneffectiveCompactions: "x" }).maxIneffectiveCompactions).toBe(2);
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
			// Mirror real pi: successful compaction fires onComplete and then the
			// session_compact event; the extension resumes from the event handler.
			// fromExtension is false because pi only sets it when a
			// session_before_compact handler supplied the compaction content.
			compact: ({ onComplete }: { onComplete: () => void }) => {
				compactCalls += 1;
				onComplete();
				handlers.get("session_compact")?.({ fromExtension: false, willRetry: false }, ctx);
			},
		};
		handlers.get("turn_end")?.({}, ctx);
		handlers.get("agent_end")?.({}, ctx);

		expect(compactCalls).toBe(1);
		expect(commands).toContain("auto-compact");
		expect(followUps).toEqual([{ text: DEFAULT_CONTINUATION, options: { deliverAs: "followUp" } }]);
	});

	test("does not resume when core overflow recovery already retries (willRetry)", () => {
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
				handlers.get("session_compact")?.({ fromExtension: false, willRetry: true }, ctx);
			},
		};
		handlers.get("turn_end")?.({}, ctx);
		expect(followUps).toEqual([]);
	});

	test("does not consume the pending resume for compactions it did not trigger", () => {
		const handlers = new Map<string, (event: unknown, ctx: any) => void>();
		const followUps: string[] = [];
		extension({
			on: (name: string, handler: (event: unknown, ctx: any) => void) => handlers.set(name, handler),
			registerCommand: () => {},
			sendUserMessage: (text: string) => {
				followUps.push(text);
			},
		} as any);

		handlers.get("session_compact")?.({ fromExtension: false, willRetry: false }, { hasUI: false });
		expect(followUps).toEqual([]);
	});

	test("survives a stale runtime when compact settles after session dispose", () => {
		const handlers = new Map<string, (event: unknown, ctx: any) => void>();
		extension({
			on: (name: string, handler: (event: unknown, ctx: any) => void) => handlers.set(name, handler),
			registerCommand: () => {},
			// Mirror real pi: after dispose() the runtime is invalidated and every
			// action method throws the stale-ctx error.
			sendUserMessage: () => {
				throw new Error("This extension ctx is stale after session replacement or reload.");
			},
		} as any);

		const ctx = {
			hasUI: false,
			getContextUsage: () => ({ tokens: 148_800, contextWindow: 372_000 }),
			// dispose() -> abortCompaction() -> pending compact promise rejects.
			compact: ({ onError }: { onError: (error: Error) => void }) => {
				onError(new Error("Compaction aborted"));
			},
		};
		expect(() => handlers.get("turn_end")?.({}, ctx)).not.toThrow();
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

	test("circuit breaker pauses auto-compaction after N ineffective (rising-token) compactions", () => {
		const handlers = new Map<string, (event: unknown, ctx: any) => void>();
		extension({
			on: (name: string, handler: (event: unknown, ctx: any) => void) => handlers.set(name, handler),
			registerCommand: () => {},
			sendUserMessage: () => {},
		} as any);

		// Compaction never reduces context; tokens keep climbing above threshold,
		// so each agent_end re-triggers (rising tokens defeat the same-count guard).
		let tokens = 148_800;
		let compactCalls = 0;
		const ctx = {
			hasUI: false,
			getContextUsage: () => ({ tokens, contextWindow: 372_000 }),
			compact: ({ onComplete }: { onComplete: () => void }) => {
				compactCalls += 1;
				onComplete();
				handlers.get("session_compact")?.({ fromExtension: true, willRetry: false }, ctx);
				tokens += 1_000; // ineffective: context grows, never drops below threshold
			},
		};

		// Default breaker limit is 2: attempt #1 triggers, attempt #2 is the first
		// re-trigger (count 1), attempt #3 would be count 2 -> breaker trips first.
		for (let i = 0; i < 6; i++) handlers.get("agent_end")?.({}, ctx);
		expect(compactCalls).toBe(2);

		// session_start resets the breaker.
		handlers.get("session_start")?.({}, ctx);
		for (let i = 0; i < 6; i++) handlers.get("agent_end")?.({}, ctx);
		expect(compactCalls).toBe(4);
	});

	test("tokens:null after compaction does not reset the breaker or re-trigger", () => {
		const handlers = new Map<string, (event: unknown, ctx: any) => void>();
		extension({
			on: (name: string, handler: (event: unknown, ctx: any) => void) => handlers.set(name, handler),
			registerCommand: () => {},
			sendUserMessage: () => {},
		} as any);

		// After each compaction the reading is null (no post-compaction assistant
		// usage yet); then a real rising reading arrives. null must neither trigger
		// nor clear the breaker counter.
		const readings: Array<{ tokens: number | null; contextWindow: number }> = [
			{ tokens: 148_800, contextWindow: 372_000 }, // trigger #1
			{ tokens: null, contextWindow: 372_000 }, // post-compaction, no-op
			{ tokens: 150_000, contextWindow: 372_000 }, // re-trigger (count 1)
			{ tokens: null, contextWindow: 372_000 }, // post-compaction, no-op
			{ tokens: 151_000, contextWindow: 372_000 }, // re-trigger -> breaker trips (count 2)
			{ tokens: 152_000, contextWindow: 372_000 }, // paused, no compaction
		];
		let idx = 0;
		let compactCalls = 0;
		const ctx = {
			hasUI: false,
			getContextUsage: () => readings[Math.min(idx, readings.length - 1)],
			compact: ({ onComplete }: { onComplete: () => void }) => {
				compactCalls += 1;
				onComplete();
				handlers.get("session_compact")?.({ fromExtension: true, willRetry: false }, ctx);
			},
		};
		for (idx = 0; idx < readings.length; idx++) handlers.get("agent_end")?.({}, ctx);
		expect(compactCalls).toBe(2);
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
