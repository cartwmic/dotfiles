import { describe, expect, test } from "bun:test";
import { mkdtempSync, readFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { registerAutoCompactExtension } from "./index.ts";
import { AUTO_COMPACT_WILL_RESUME_EVENT } from "./events.ts";
import {
	DEFAULT_CONFIG,
	DEFAULT_CONTINUATION,
	breakerCooldownMs,
	describeConfig,
	normalizeConfig,
	normalizeContinuation,
	resumeAfterCompact,
	shouldTrigger,
	thresholdTokens,
} from "./config.ts";

// Tests never write the real log beside the extension.
const extension = (pi: any, options: Record<string, unknown> = {}): void => {
	registerAutoCompactExtension(pi, { config: DEFAULT_CONFIG, logPath: null, ...options });
};

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
			`auto-compaction ON; threshold 40% or 200,000 tokens, whichever is lower; check at turn_end + agent_end; continuation "${DEFAULT_CONTINUATION}"; breaker 2, retry after 300s (doubling)`,
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
		expect(normalizeConfig(undefined).breakerCooldownSeconds).toBe(300);
		expect(normalizeConfig({ breakerCooldownSeconds: 0 }).breakerCooldownSeconds).toBe(0);
		expect(normalizeConfig({ breakerCooldownSeconds: 90.9 }).breakerCooldownSeconds).toBe(90);
		expect(normalizeConfig({ breakerCooldownSeconds: -1 }).breakerCooldownSeconds).toBe(300);
		expect(normalizeConfig({ breakerCooldownSeconds: "x" }).breakerCooldownSeconds).toBe(300);
		expect(describeConfig({ ...DEFAULT_CONFIG, breakerCooldownSeconds: 0 })).toContain("no retry");
		expect(breakerCooldownMs(300, 1)).toBe(300_000);
		expect(breakerCooldownMs(300, 2)).toBe(600_000);
		expect(breakerCooldownMs(300, 9)).toBe(3_600_000);
		expect(breakerCooldownMs(0, 1)).toBeUndefined();
	});

	test("resumes only after inter-turn compaction when continuation is enabled", () => {
		expect(resumeAfterCompact(DEFAULT_CONFIG, "turn_end", true)).toBe(DEFAULT_CONTINUATION);
		expect(resumeAfterCompact(DEFAULT_CONFIG, "turn_end", false)).toBeUndefined();
		expect(resumeAfterCompact(DEFAULT_CONFIG, "agent_end", false)).toBeUndefined();
		expect(
			resumeAfterCompact({ ...DEFAULT_CONFIG, continuation: false }, "turn_end", true),
		).toBeUndefined();
		expect(
			resumeAfterCompact({ ...DEFAULT_CONFIG, continuation: "Keep going." }, "turn_end", true),
		).toBe("Keep going.");
	});
});

describe("auto-compact absolute cap", () => {
	test("defaults to 200000 tokens, and an old config without the key gets it", () => {
		expect(DEFAULT_CONFIG.thresholdTokens).toBe(200_000);
		expect(normalizeConfig({ enabled: true, thresholdPercent: 40, continuation: "x" }).thresholdTokens).toBe(200_000);
	});

	test("normalizes the cap (custom, floor, invalid)", () => {
		expect(normalizeConfig({ thresholdTokens: 150_000 }).thresholdTokens).toBe(150_000);
		expect(normalizeConfig({ thresholdTokens: 150_000.9 }).thresholdTokens).toBe(150_000);
		for (const bad of [0, -5, "x", null, Number.NaN, Infinity]) {
			expect(normalizeConfig({ thresholdTokens: bad }).thresholdTokens).toBe(200_000);
		}
	});

	test("fires at whichever comes first: the percentage or the cap", () => {
		expect(thresholdTokens(1_000_000, 40, 200_000)).toBe(200_000); // 400k by percent, so the cap wins
		expect(thresholdTokens(272_000, 40, 200_000)).toBe(108_800); // 40% is lower than the cap, so it wins
		expect(thresholdTokens(872_000, 40, 200_000)).toBe(200_000);
		expect(thresholdTokens(1_000_000, 40)).toBe(400_000); // no cap given: unchanged behaviour
		expect(thresholdTokens(1_000_000, 40, 0)).toBe(400_000); // an unusable cap is ignored
		expect(thresholdTokens(1_000_000, 10, 200_000)).toBe(100_000); // a cap never raises the percentage
	});

	test("shouldTrigger uses the cap, inclusively", () => {
		expect(shouldTrigger(DEFAULT_CONFIG, "turn_end", { tokens: 199_999, contextWindow: 1_000_000 })).toBe(false);
		expect(shouldTrigger(DEFAULT_CONFIG, "turn_end", { tokens: 200_000, contextWindow: 1_000_000 })).toBe(true);
		expect(shouldTrigger(DEFAULT_CONFIG, "turn_end", { tokens: 108_799, contextWindow: 272_000 })).toBe(false);
		expect(shouldTrigger(DEFAULT_CONFIG, "turn_end", { tokens: 108_800, contextWindow: 272_000 })).toBe(true);
		const lower = normalizeConfig({ thresholdTokens: 150_000 });
		expect(shouldTrigger(lower, "turn_end", { tokens: 150_000, contextWindow: 1_000_000 })).toBe(true);
	});

	// Black box: the registered extension, driven through Pi's events, compacts a session at the right size.
	const compactsAt = (contextWindow: number, tokens: number, config = DEFAULT_CONFIG): number => {
		const handlers = new Map<string, (event: any, ctx: any) => void>();
		extension(
			{
				on: (name: string, handler: (event: any, ctx: any) => void) => handlers.set(name, handler),
				registerCommand: () => {},
				sendUserMessage: () => {},
				events: { emit: () => {} },
			} as any,
			{ config },
		);
		let compactCalls = 0;
		const ctx = {
			hasUI: false,
			getContextUsage: () => ({ tokens, contextWindow }),
			compact: ({ onComplete }: { onComplete: () => void }) => {
				compactCalls += 1;
				onComplete();
			},
		};
		handlers.get("turn_end")?.({}, ctx);
		handlers.get("turn_start")?.({}, ctx);
		return compactCalls;
	};

	test("a 1M-window session compacts at 200k, not 400k", () => {
		expect(compactsAt(1_000_000, 199_999)).toBe(0);
		expect(compactsAt(1_000_000, 200_000)).toBe(1);
		expect(compactsAt(1_000_000, 399_999)).toBe(1);
	});

	test("a 272k-window session still compacts at 40%, about 109k", () => {
		expect(compactsAt(272_000, 108_799)).toBe(0);
		expect(compactsAt(272_000, 108_800)).toBe(1);
	});

	test("a 872k-window session compacts at the cap", () => {
		expect(compactsAt(872_000, 199_999)).toBe(0);
		expect(compactsAt(872_000, 200_000)).toBe(1);
	});

	test("the breaker judges recovery against the capped threshold", () => {
		const handlers = new Map<string, (event: any, ctx: any) => void>();
		const notices: string[] = [];
		extension({
			on: (name: string, handler: (event: any, ctx: any) => void) => handlers.set(name, handler),
			registerCommand: () => {},
			sendUserMessage: () => {},
			appendEntry: () => {},
			events: { emit: () => {} },
		} as any);
		let tokens = 250_000; // above the 200k cap, below 40% of 1M: only the cap makes this "over threshold"
		let compactCalls = 0;
		const ctx: any = {
			hasUI: true,
			ui: { notify: (m: string) => notices.push(m) },
			getContextUsage: () => ({ tokens, contextWindow: 1_000_000 }),
			compact: ({ onComplete }: { onComplete: () => void }) => {
				compactCalls += 1;
				onComplete();
				tokens += 1_000; // a compaction that does not shrink the context
			},
		};
		for (let i = 0; i < 6; i++) handlers.get("agent_settled")?.({}, ctx);
		expect(compactCalls).toBe(2);
		expect(notices.some((n) => n.includes("paused") && n.includes("below 200,000 tokens"))).toBe(true);
	});

	test("a configured cap above the percentage changes nothing", () => {
		const config = normalizeConfig({ thresholdTokens: 900_000 });
		expect(compactsAt(1_000_000, 399_999, config)).toBe(0);
		expect(compactsAt(1_000_000, 400_000, config)).toBe(1);
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

	test("never compacts at agent_end — a queued continuation may still run", () => {
		// agent_end is a low-level attempt boundary: Pi can still run a native
		// retry or a continuation queued by another extension's agent_end handler
		// (e.g. the goal loop's follow-up). Compacting there can preempt work Pi
		// has not yet surfaced through its final agent_settled boundary.
		const handlers = new Map<string, (event: unknown, ctx: any) => void>();
		extension({
			on: (name: string, handler: (event: unknown, ctx: any) => void) => handlers.set(name, handler),
			registerCommand: () => {},
			sendUserMessage: () => {},
		} as any);

		expect(handlers.has("agent_end")).toBe(false);
		expect(handlers.has("agent_settled")).toBe(true);
	});

	test("resumes only after successful compaction fully completes", () => {
		const handlers = new Map<string, (event: unknown, ctx: any) => void>();
		const commands: string[] = [];
		const emitted: string[] = [];
		const followUps: Array<{
			text: string;
			options?: { deliverAs?: string };
			duringCompaction: boolean;
		}> = [];
		let compactionInProgress = false;
		extension({
			on: (name: string, handler: (event: unknown, ctx: any) => void) => handlers.set(name, handler),
			registerCommand: (name: string) => commands.push(name),
			sendUserMessage: (text: string, options?: { deliverAs?: string }) => {
				followUps.push({ text, options, duringCompaction: compactionInProgress });
			},
			events: { emit: (name: string) => emitted.push(name) },
		} as any);

		let compactCalls = 0;
		const ctx = {
			hasUI: false,
			getContextUsage: () => ({ tokens: 148_800, contextWindow: 372_000 }),
			compact: ({ onComplete }: { onComplete: () => void }) => {
				compactCalls += 1;
				compactionInProgress = true;
				// Real Pi ordering: compact() aborts the active run, emits
				// agent_settled and session_compact while its compaction controller is
				// still active, then clears the controller before invoking onComplete.
				handlers.get("agent_settled")?.({}, ctx);
				handlers.get("session_compact")?.({ fromExtension: false, willRetry: false }, ctx);
				compactionInProgress = false;
				onComplete();
			},
		};
		handlers.get("turn_end")?.({}, ctx);
		expect(compactCalls).toBe(0);
		handlers.get("turn_start")?.({}, ctx);

		expect(compactCalls).toBe(1);
		expect(commands).toContain("auto-compact");
		expect(emitted).toEqual([AUTO_COMPACT_WILL_RESUME_EVENT]);
		expect(followUps).toEqual([
			{
				text: DEFAULT_CONTINUATION,
				options: { deliverAs: "followUp" },
				duringCompaction: false,
			},
		]);
	});

	for (const outcome of ["complete", "error"] as const) {
		test(`user input flushed before ${outcome} replaces the continuation`, () => {
			const handlers = new Map<string, (event: any, ctx: any) => void>();
			const followUps: string[] = [];
			extension({
				on: (name: string, handler: (event: any, ctx: any) => void) => handlers.set(name, handler),
				registerCommand: () => {},
				sendUserMessage: (text: string) => followUps.push(text),
			} as any);
			const ctx = {
				hasUI: false,
				getContextUsage: () => ({ tokens: 148_800, contextWindow: 372_000 }),
				compact: (cb: { onComplete: () => void; onError: (e: Error) => void }) => {
					// Real Pi ordering: compaction_end flushes the TUI queue through
					// prompt(), which emits input before compact() returns.
					handlers.get("input")?.({ type: "input", text: "STEER", source: "interactive" }, ctx);
					if (outcome === "complete") cb.onComplete();
					else cb.onError(new Error("summary failed"));
				},
			};
			handlers.get("turn_end")?.({}, ctx);
			handlers.get("turn_start")?.({}, ctx);
			expect(followUps).toEqual([]);
		});
	}

	test("user input seen after onComplete drops the continuation at its own input event", () => {
		const handlers = new Map<string, (event: any, ctx: any) => any>();
		const followUps: string[] = [];
		extension({
			on: (name: string, handler: (event: any, ctx: any) => any) => handlers.set(name, handler),
			registerCommand: () => {},
			sendUserMessage: (text: string) => followUps.push(text),
		} as any);
		const ctx = {
			hasUI: false,
			getContextUsage: () => ({ tokens: 148_800, contextWindow: 372_000 }),
			compact: ({ onComplete }: { onComplete: () => void }) => onComplete(),
		};
		handlers.get("turn_end")?.({}, ctx);
		handlers.get("turn_start")?.({}, ctx);
		// An earlier extension's async input handler delayed the user's message
		// past onComplete, so the continuation was already sent.
		expect(followUps).toEqual([DEFAULT_CONTINUATION]);
		expect(handlers.get("input")?.({ type: "input", text: "STEER", source: "interactive" }, ctx)).toBeUndefined();
		expect(handlers.get("input")?.({ type: "input", text: DEFAULT_CONTINUATION, source: "extension" }, ctx)).toEqual({
			action: "handled",
		});
	});

	test("continuation passes its input event when the user did not speak", () => {
		const handlers = new Map<string, (event: any, ctx: any) => any>();
		extension({
			on: (name: string, handler: (event: any, ctx: any) => any) => handlers.set(name, handler),
			registerCommand: () => {},
			sendUserMessage: () => {},
		} as any);
		const ctx = {
			hasUI: false,
			getContextUsage: () => ({ tokens: 148_800, contextWindow: 372_000 }),
			compact: ({ onComplete }: { onComplete: () => void }) => onComplete(),
		};
		handlers.get("turn_end")?.({}, ctx);
		handlers.get("turn_start")?.({}, ctx);
		expect(handlers.get("input")?.({ type: "input", text: DEFAULT_CONTINUATION, source: "extension" }, ctx)).toBeUndefined();
		// Later user input is ordinary and no longer tied to the delivered continuation.
		expect(handlers.get("input")?.({ type: "input", text: "later", source: "interactive" }, ctx)).toBeUndefined();
	});

	test("extension-sourced input does not cancel the continuation", () => {
		const handlers = new Map<string, (event: any, ctx: any) => void>();
		const followUps: string[] = [];
		extension({
			on: (name: string, handler: (event: any, ctx: any) => void) => handlers.set(name, handler),
			registerCommand: () => {},
			sendUserMessage: (text: string) => followUps.push(text),
		} as any);
		const ctx = {
			hasUI: false,
			getContextUsage: () => ({ tokens: 148_800, contextWindow: 372_000 }),
			compact: ({ onComplete }: { onComplete: () => void }) => {
				handlers.get("input")?.({ type: "input", text: "x", source: "extension" }, ctx);
				onComplete();
			},
		};
		handlers.get("turn_end")?.({}, ctx);
		handlers.get("turn_start")?.({}, ctx);
		expect(followUps).toEqual([DEFAULT_CONTINUATION]);
	});

	test("user input outside compaction does not cancel a later continuation", () => {
		const handlers = new Map<string, (event: any, ctx: any) => void>();
		const followUps: string[] = [];
		extension({
			on: (name: string, handler: (event: any, ctx: any) => void) => handlers.set(name, handler),
			registerCommand: () => {},
			sendUserMessage: (text: string) => followUps.push(text),
		} as any);
		const ctx = {
			hasUI: false,
			getContextUsage: () => ({ tokens: 148_800, contextWindow: 372_000 }),
			compact: ({ onComplete }: { onComplete: () => void }) => onComplete(),
		};
		handlers.get("input")?.({ type: "input", text: "earlier", source: "interactive" }, ctx);
		handlers.get("turn_end")?.({}, ctx);
		handlers.get("turn_start")?.({}, ctx);
		expect(followUps).toEqual([DEFAULT_CONTINUATION]);
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
				handlers.get("session_compact")?.({ fromExtension: false, willRetry: true }, ctx);
				onComplete();
			},
		};
		handlers.get("turn_end")?.({}, ctx);
		handlers.get("turn_start")?.({}, ctx);
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
		handlers.get("turn_end")?.({}, ctx);
		expect(() => handlers.get("turn_start")?.({}, ctx)).not.toThrow();
	});

	test("does not resume or signal when the final turn is followed by agent_settled", () => {
		const handlers = new Map<string, (event: unknown, ctx: any) => void>();
		const emitted: string[] = [];
		const followUps: string[] = [];
		extension({
			on: (name: string, handler: (event: unknown, ctx: any) => void) => handlers.set(name, handler),
			registerCommand: () => {},
			sendUserMessage: (text: string) => {
				followUps.push(text);
			},
			events: { emit: (name: string) => emitted.push(name) },
		} as any);

		let compactCalls = 0;
		const ctx = {
			hasUI: false,
			getContextUsage: () => ({ tokens: 148_800, contextWindow: 372_000 }),
			compact: ({ onComplete }: { onComplete: () => void }) => {
				compactCalls += 1;
				handlers.get("session_compact")?.({ fromExtension: false, willRetry: false }, ctx);
				onComplete();
			},
		};
		handlers.get("turn_end")?.({}, ctx);
		expect(compactCalls).toBe(0);
		handlers.get("agent_settled")?.({}, ctx);
		expect(compactCalls).toBe(1);
		expect(emitted).toEqual([]);
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
		// so each agent_settled re-triggers (rising tokens defeat the same-count guard).
		let tokens = 148_800;
		let compactCalls = 0;
		const ctx = {
			hasUI: false,
			getContextUsage: () => ({ tokens, contextWindow: 372_000 }),
			compact: ({ onComplete }: { onComplete: () => void }) => {
				compactCalls += 1;
				handlers.get("session_compact")?.({ fromExtension: true, willRetry: false }, ctx);
				onComplete();
				tokens += 1_000; // ineffective: context grows, never drops below threshold
			},
		};

		// Default breaker limit is 2: attempt #1 triggers, attempt #2 is the first
		// re-trigger (count 1), attempt #3 would be count 2 -> breaker trips first.
		for (let i = 0; i < 6; i++) handlers.get("agent_settled")?.({}, ctx);
		expect(compactCalls).toBe(2);

		// session_start resets the breaker.
		handlers.get("session_start")?.({}, ctx);
		for (let i = 0; i < 6; i++) handlers.get("agent_settled")?.({}, ctx);
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
				handlers.get("session_compact")?.({ fromExtension: true, willRetry: false }, ctx);
				onComplete();
			},
		};
		for (idx = 0; idx < readings.length; idx++) handlers.get("agent_settled")?.({}, ctx);
		expect(compactCalls).toBe(2);
	});

	test("resumes on compact error after inter-turn abort", () => {
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
		handlers.get("turn_start")?.({}, ctx);
		expect(followUps).toEqual([DEFAULT_CONTINUATION]);
	});
});

// Session entries other than the pause markers (compacting / compacted).
const events = (entries: Array<{ type: string; data: any }>) =>
	entries.filter((e) => e.data.kind !== "compacting" && e.data.kind !== "compacted");

describe("auto-compact breaker visibility and retry", () => {
	const setup = (options: Record<string, unknown> = {}, ui = false) => {
		const handlers = new Map<string, (event: unknown, ctx: any) => void>();
		const commands = new Map<string, any>();
		const entries: Array<{ type: string; data: any }> = [];
		const notices: string[] = [];
		let clock = 1_000_000;
		const logPath = join(mkdtempSync(join(tmpdir(), "auto-compact-")), "auto-compact.log");
		extension(
			{
				on: (name: string, handler: (event: unknown, ctx: any) => void) => handlers.set(name, handler),
				registerCommand: (name: string, def: unknown) => commands.set(name, def),
				sendUserMessage: () => {},
				appendEntry: (type: string, data: any) => entries.push({ type, data }),
			},
			{ logPath, now: () => clock, ...options },
		);
		let tokens = 148_800;
		let mode: "ineffective" | "fail" | "effective" = "ineffective";
		let compactCalls = 0;
		const ctx: any = {
			hasUI: ui,
			ui: { notify: (m: string) => notices.push(m) },
			getContextUsage: () => ({ tokens, contextWindow: 372_000 }),
			compact: ({ onComplete, onError }: { onComplete: () => void; onError: (e: Error) => void }) => {
				compactCalls += 1;
				if (mode === "fail") {
					onError(new Error("Summarization failed: generation hit the token cap"));
				} else {
					handlers.get("session_compact")?.({ fromExtension: true, willRetry: false }, ctx);
					onComplete();
				}
				if (mode === "effective") tokens = 50_000;
				else tokens += 1_000;
			},
		};
		const settle = (n = 1) => {
			for (let i = 0; i < n; i++) handlers.get("agent_settled")?.({}, ctx);
		};
		return {
			ctx, settle, entries, notices, logPath, commands, handlers,
			calls: () => compactCalls,
			advance: (ms: number) => { clock += ms; },
			setTokens: (n: number) => { tokens = n; },
			setMode: (m: "ineffective" | "fail" | "effective") => { mode = m; },
			log: () => (existsSync(logPath) ? readFileSync(logPath, "utf8").trim().split("\n").map((l) => JSON.parse(l)) : []),
		};
	};

	test("a tripped breaker is recorded in the log and the session, and warns in the UI", () => {
		const t = setup({}, true);
		t.settle(6);
		expect(t.calls()).toBe(2);
		const logged = t.log();
		expect(logged.map((e: any) => e.kind)).toEqual(["breaker_paused"]);
		expect(logged[0]).toMatchObject({ thresholdPercent: 40, consecutiveIneffective: 2, retryInSeconds: 300 });
		expect(t.entries.every((e) => e.type === "auto-compact")).toBe(true);
		expect(events(t.entries).map((e) => e.data.kind)).toEqual(["breaker_paused"]);
		expect(t.notices.some((n) => n.includes("paused") && n.includes("retry once in 300s"))).toBe(true);
	});

	test("a headless session still gets the log and session entries", () => {
		const t = setup({}, false);
		t.settle(6);
		expect(t.notices).toEqual([]);
		expect(t.log().map((e: any) => e.kind)).toEqual(["breaker_paused"]);
		expect(events(t.entries).length).toBe(1);
	});

	test("after the cooldown exactly one retry runs, then it pauses again with a doubled wait", () => {
		const t = setup();
		t.settle(6);
		expect(t.calls()).toBe(2);
		t.advance(299_000);
		t.settle(3);
		expect(t.calls()).toBe(2);
		t.advance(2_000);
		t.settle(6);
		expect(t.calls()).toBe(3);
		expect(t.log().map((e: any) => e.kind)).toEqual(["breaker_paused", "breaker_retry", "breaker_paused"]);
		expect(t.log()[2].retryInSeconds).toBe(600);
		t.advance(599_000);
		t.settle(3);
		expect(t.calls()).toBe(3);
		t.advance(2_000);
		t.settle(6);
		expect(t.calls()).toBe(4);
		expect(t.log()[4].retryInSeconds).toBe(1200);
	});

	test("a successful retry clears the pause and the doubling", () => {
		const t = setup();
		t.settle(6); // trip #1 (300s)
		t.advance(301_000);
		t.settle(6); // retry runs, still ineffective: trip #2 (600s)
		expect(t.log()[2].retryInSeconds).toBe(600);
		t.advance(601_000);
		t.setMode("effective");
		t.settle(1); // retry succeeds: context drops below threshold
		expect(t.ctx.getContextUsage().tokens).toBeLessThan(148_800);
		t.settle(1); // finite below-threshold reading clears breaker state and backoff
		t.setMode("ineffective");
		t.setTokens(148_800); // context climbs back to the threshold
		t.settle(6); // fresh breaker: 2 attempts, then trip
		const paused = t.log().filter((e: any) => e.kind === "breaker_paused");
		expect(paused[paused.length - 1].retryInSeconds).toBe(300); // not 1200
	});

	test("recovery while paused (manual compact) lifts the pause and resets backoff", () => {
		const t = setup();
		t.settle(6);
		expect(t.calls()).toBe(2);
		t.setTokens(50_000); // user compacted by hand during the cooldown
		t.settle(1);
		t.setTokens(148_800);
		t.settle(6); // no cooldown wait: the breaker was reset
		expect(t.calls()).toBe(4);
		const paused = t.log().filter((e: any) => e.kind === "breaker_paused");
		expect(paused[paused.length - 1].retryInSeconds).toBe(300);
	});

	test("an expired pause is not recorded as a retry until a compaction actually starts", () => {
		const t = setup({ config: { ...DEFAULT_CONFIG, checkAt: ["agent_end"] } });
		t.settle(6);
		t.advance(301_000);
		t.handlers.get("turn_end")?.({}, t.ctx);
		t.handlers.get("turn_start")?.({}, t.ctx); // turn_end is not a configured checkpoint: no attempt, no retry event
		expect(t.log().map((e: any) => e.kind)).toEqual(["breaker_paused"]);
		t.settle(1);
		expect(t.log().map((e: any) => e.kind)).toEqual(["breaker_paused", "breaker_retry"]);
	});

	test("breakerCooldownSeconds 0 keeps the permanent pause until reload", () => {
		const t = setup({ config: { ...DEFAULT_CONFIG, breakerCooldownSeconds: 0 } });
		t.settle(6);
		expect(t.log()[0].retryInSeconds).toBeNull();
		t.advance(10 * 3_600_000);
		t.settle(6);
		expect(t.calls()).toBe(2);
		expect(t.log().map((e: any) => e.kind)).toEqual(["breaker_paused"]);
	});

	test("a failed compaction is logged with its error and counts toward the breaker", () => {
		const t = setup({}, true);
		t.setMode("fail");
		t.settle(6);
		const kinds = t.log().map((e: any) => e.kind);
		expect(kinds.filter((k: string) => k === "compaction_failed").length).toBe(2);
		expect(kinds[kinds.length - 1]).toBe("breaker_paused");
		expect(t.log()[0].error).toContain("token cap");
		expect(t.notices.some((n) => n.startsWith("Auto-compaction failed"))).toBe(true);
	});

	test("/auto-compact status shows the pause and the retry time", () => {
		const t = setup({}, true);
		t.settle(6);
		t.notices.length = 0;
		t.commands.get("auto-compact").handler("status", t.ctx);
		expect(t.notices[0]).toContain("PAUSED, retry after");
		t.commands.get("auto-compact").handler("reload", t.ctx);
		t.notices.length = 0;
		t.commands.get("auto-compact").handler("status", t.ctx);
		expect(t.notices[0]).not.toContain("PAUSED");
	});

	test("an unwritable log never breaks compaction", () => {
		const t = setup({ logPath: "/nonexistent-dir/x/auto-compact.log" });
		t.settle(6);
		expect(t.calls()).toBe(2);
		expect(events(t.entries).length).toBe(1);
	});
});

describe("auto-compact pause markers", () => {
	// One ordered log of what the extension does: session entries, compact() calls and continuations.
	const setup = (compact: (cb: any, h: Map<string, (event: any, ctx: any) => any>) => void, options: Record<string, unknown> = {}, send?: (text: string) => void) => {
		const handlers = new Map<string, (event: any, ctx: any) => any>();
		const steps: Array<{ step: string; data?: any }> = [];
		extension(
			{
				on: (name: string, handler: (event: any, ctx: any) => any) => handlers.set(name, handler),
				registerCommand: () => {},
				sendUserMessage: send ?? ((text: string) => steps.push({ step: "send", data: text })),
				appendEntry: (type: string, data: any) => steps.push({ step: type, data }),
				events: { emit: () => {} },
			} as any,
			options,
		);
		const ctx = {
			hasUI: false,
			getContextUsage: () => ({ tokens: 148_800, contextWindow: 372_000 }),
			compact: (cb: any) => {
				steps.push({ step: "compact" });
				compact(cb, handlers);
			},
		};
		return { handlers, steps, ctx, markers: () => steps.filter((s) => s.step === "auto-compact").map((s) => s.data) };
	};
	const interTurn = (t: ReturnType<typeof setup>) => {
		t.handlers.get("turn_end")?.({}, t.ctx);
		t.handlers.get("turn_start")?.({}, t.ctx);
	};

	test("an inter-turn pause: compacting before the abort, compacted (resumeSent) before the continuation", () => {
		const t = setup((cb) => cb.onComplete());
		interTurn(t);
		expect(t.steps.map((s) => (s.step === "auto-compact" ? s.data.kind : s.step))).toEqual(["compacting", "compact", "compacted", "send"]);
		expect(t.markers()[0]).toMatchObject({ kind: "compacting", resume: true, tokens: 148_800, contextWindow: 372_000, checkPoint: "turn_end" });
		expect(t.markers()[1]).toMatchObject({ kind: "compacted", resumeSent: true });
		expect(typeof t.markers()[0].at).toBe("string");
	});

	test("a message typed during compaction: compacted says resumeSent false", () => {
		const t = setup((cb, h) => {
			h.get("input")?.({ type: "input", text: "STEER", source: "interactive" }, {});
			cb.onComplete();
		});
		interTurn(t);
		expect(t.markers().map((m) => [m.kind, m.resumeSent])).toEqual([["compacting", undefined], ["compacted", false]]);
		expect(t.steps.some((s) => s.step === "send")).toBe(false);
	});

	test("a message typed during compaction that reaches input after onComplete: a second closing marker says resumeSent false", () => {
		const t = setup((cb) => cb.onComplete());
		interTurn(t);
		t.handlers.get("input")?.({ type: "input", text: "STEER", source: "interactive" }, {});
		expect(t.handlers.get("input")?.({ type: "input", text: DEFAULT_CONTINUATION, source: "extension" }, {})).toEqual({ action: "handled" });
		expect(t.markers().map((m) => [m.kind, m.resumeSent])).toEqual([["compacting", undefined], ["compacted", true], ["compacted", false]]);
		expect(t.markers()[2].error).toBe("continuation replaced by a user message");
	});

	test("a final compaction (agent_settled) is marked with no resume", () => {
		const t = setup((cb) => cb.onComplete());
		t.handlers.get("agent_settled")?.({}, t.ctx);
		expect(t.markers().map((m) => [m.kind, m.resume ?? m.resumeSent])).toEqual([["compacting", false], ["compacted", false]]);
	});

	test("a failed compaction closes the pause with compaction_failed, before the continuation", () => {
		const t = setup((cb) => cb.onError(new Error("summary failed")));
		interTurn(t);
		expect(t.steps.map((s) => (s.step === "auto-compact" ? s.data.kind : s.step))).toEqual(["compacting", "compact", "compaction_failed", "send"]);
		expect(t.markers()[1]).toMatchObject({ kind: "compaction_failed", resumeSent: true, error: "summary failed" });
	});

	test("a continuation that cannot be submitted gets a second closing marker with resumeSent false", () => {
		for (const [finish, kind] of [[(cb: any) => cb.onComplete(), "compacted"], [(cb: any) => cb.onError(new Error("summary failed")), "compaction_failed"]] as const) {
			const t = setup(finish, {}, () => {
				throw new Error("This extension ctx is stale after session replacement or reload.");
			});
			interTurn(t);
			expect(t.markers().map((m) => [m.kind, m.resumeSent])).toEqual([["compacting", undefined], [kind, true], [kind, false]]);
			expect(t.markers()[2].error).toContain("continuation not submitted: This extension ctx is stale");
		}
	});

	test("compact() throwing at once closes the pause with resumeSent false", () => {
		const t = setup(() => {
			throw new Error("no model");
		});
		interTurn(t);
		expect(t.markers().map((m) => [m.kind, m.resumeSent])).toEqual([["compacting", undefined], ["compaction_failed", false]]);
	});

	test("a session shut down during compaction closes the pause; after compaction it writes nothing", () => {
		const t = setup(() => {}); // compaction never finishes
		interTurn(t);
		t.handlers.get("session_shutdown")?.({}, t.ctx);
		expect(t.markers().map((m) => [m.kind, m.resumeSent])).toEqual([["compacting", undefined], ["compaction_failed", false]]);
		const done = setup((cb) => cb.onComplete());
		interTurn(done);
		done.handlers.get("session_shutdown")?.({}, done.ctx);
		expect(done.markers().map((m) => m.kind)).toEqual(["compacting", "compacted"]);
	});
});
