import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type {
	ExtensionAPI,
	ExtensionCommandContext,
	ExtensionContext,
} from "@earendil-works/pi-coding-agent";
import {
	type AutoCompactConfig,
	type CheckPoint,
	DEFAULT_CONTINUATION,
	describeConfig,
	describeContinuation,
	loadConfig,
	resumeAfterCompact,
	saveConfig,
	shouldTrigger,
	thresholdTokens,
} from "./config.ts";

function extensionDir(): string {
	return dirname(fileURLToPath(import.meta.url));
}

function formatError(error: unknown): string {
	return error instanceof Error ? error.message : String(error);
}

function checkPointSelection(config: AutoCompactConfig): string {
	if (config.checkAt.length === 2) return "Both: turn_end + agent_end";
	return config.checkAt[0] === "turn_end" ? "Turn end only" : "Agent end only";
}

async function configure(
	ctx: ExtensionCommandContext,
	current: AutoCompactConfig,
	path: string,
): Promise<AutoCompactConfig> {
	if (!ctx.hasUI) {
		ctx.ui.notify(`Interactive configuration requires TUI. Edit ${path}`, "warning");
		return current;
	}

	let draft: AutoCompactConfig = { ...current, checkAt: [...current.checkAt] };
	while (true) {
		const choice = await ctx.ui.select("Auto-compaction configuration", [
			`Enabled: ${draft.enabled ? "ON" : "OFF"}`,
			`Threshold: ${draft.thresholdPercent}%`,
			`Check at: ${checkPointSelection(draft)}`,
			`Continuation: ${describeContinuation(draft.continuation)}`,
			"Save and close",
			"Cancel",
		]);
		if (!choice || choice === "Cancel") return current;

		if (choice.startsWith("Enabled:")) {
			draft = { ...draft, enabled: !draft.enabled };
			continue;
		}
		if (choice.startsWith("Threshold:")) {
			const entered = await ctx.ui.input("Compaction threshold percent (0-100]", String(draft.thresholdPercent));
			if (entered === undefined) continue;
			const thresholdPercent = Number(entered.trim());
			if (!Number.isFinite(thresholdPercent) || thresholdPercent <= 0 || thresholdPercent > 100) {
				ctx.ui.notify("Threshold must be greater than 0 and at most 100", "warning");
				continue;
			}
			draft = { ...draft, thresholdPercent };
			continue;
		}
		if (choice.startsWith("Check at:")) {
			const selected = await ctx.ui.select("Check context usage at", [
				"Both: turn_end + agent_end",
				"Turn end only",
				"Agent end only",
			]);
			if (selected === "Both: turn_end + agent_end") {
				draft = { ...draft, checkAt: ["turn_end", "agent_end"] };
			} else if (selected === "Turn end only") {
				draft = { ...draft, checkAt: ["turn_end"] };
			} else if (selected === "Agent end only") {
				draft = { ...draft, checkAt: ["agent_end"] };
			}
			continue;
		}
		if (choice.startsWith("Continuation:")) {
			const selected = await ctx.ui.select("After mid-turn compaction (turn_end)", [
				"Resume with default message",
				"Resume with custom message",
				"Do not resume",
			]);
			if (selected === "Resume with default message") {
				draft = { ...draft, continuation: DEFAULT_CONTINUATION };
			} else if (selected === "Resume with custom message") {
				const currentText = draft.continuation === false ? DEFAULT_CONTINUATION : draft.continuation;
				const entered = await ctx.ui.input(
					"Continuation follow-up text (empty disables)",
					currentText,
				);
				if (entered === undefined) continue;
				const trimmed = entered.trim();
				draft = { ...draft, continuation: trimmed.length > 0 ? trimmed : false };
			} else if (selected === "Do not resume") {
				draft = { ...draft, continuation: false };
			}
			continue;
		}
		if (choice === "Save and close") {
			try {
				saveConfig(path, draft);
				ctx.ui.notify(`${describeConfig(draft)}; saved to ${path}`, "info");
				return draft;
			} catch (error) {
				ctx.ui.notify(`Could not save auto-compaction config: ${formatError(error)}`, "error");
				return current;
			}
		}
	}
}

export default function (pi: ExtensionAPI): void {
	const configPath = join(extensionDir(), "config.json");
	let config = loadConfig(configPath);
	let compacting = false;
	let lastAttemptTokens: number | undefined;
	let pendingResume: string | undefined;
	// Circuit breaker: consecutive compactions that did not bring context below
	// threshold. When it reaches config.maxIneffectiveCompactions we pause
	// auto-compaction for the rest of the session to prevent a loop. Reset on a
	// real below-threshold reading and on session start/shutdown.
	let consecutiveIneffective = 0;
	let autoDisabledForSession = false;

	const resetAttemptState = () => {
		compacting = false;
		lastAttemptTokens = undefined;
		pendingResume = undefined;
		consecutiveIneffective = 0;
		autoDisabledForSession = false;
	};

	const maybeCompact = (checkPoint: CheckPoint, ctx: ExtensionContext): void => {
		if (compacting || autoDisabledForSession) return;
		if (typeof ctx.getContextUsage !== "function" || typeof ctx.compact !== "function") return;

		const usage = ctx.getContextUsage();
		const threshold = usage ? thresholdTokens(usage.contextWindow, config.thresholdPercent) : undefined;
		// Only a real, finite below-threshold reading clears the attempt guard and
		// the breaker. Do NOT treat `tokens: null` (returned right after
		// compaction, before the next assistant response) as below-threshold: that
		// would reset the breaker every round and defeat it.
		if (
			usage &&
			threshold !== undefined &&
			typeof usage.tokens === "number" &&
			Number.isFinite(usage.tokens) &&
			usage.tokens < threshold
		) {
			lastAttemptTokens = undefined;
			consecutiveIneffective = 0;
		}
		if (!shouldTrigger(config, checkPoint, usage, lastAttemptTokens)) return;

		const tokens = usage!.tokens;
		const contextWindow = usage!.contextWindow;

		// A re-trigger (lastAttemptTokens still set) means the previous compaction
		// did not drop context below threshold. Count it; trip the breaker once we
		// hit the configured limit.
		if (lastAttemptTokens !== undefined) {
			consecutiveIneffective += 1;
			if (consecutiveIneffective >= config.maxIneffectiveCompactions) {
				autoDisabledForSession = true;
				if (ctx.hasUI) {
					ctx.ui.notify(
						`Auto-compaction paused for this session: ${consecutiveIneffective} consecutive compactions did not reduce context below ${config.thresholdPercent}%. Use /auto-compact reload to re-enable.`,
						"warning",
					);
				}
				return;
			}
		}

		lastAttemptTokens = tokens;
		compacting = true;
		if (ctx.hasUI) {
			ctx.ui.notify(
				`Auto-compaction: ${tokens.toLocaleString()}/${contextWindow.toLocaleString()} tokens at ${checkPoint}; compacting`,
				"info",
			);
		}

		// ctx.compact() aborts the active agent first. After mid-turn compaction,
		// re-inject so the interrupted run can continue. Skip agent_end (resume is
		// undefined there): the run already finished and a follow-up would
		// spuriously start new work.
		//
		// The success-path resume is delivered from the session_compact event
		// handler below, never from the onComplete/onError callbacks: those are
		// detached continuations that can fire after session dispose() has
		// invalidated the extension runtime (dispose -> abortCompaction -> the
		// pending compact promise rejects -> onError runs against a stale ctx).
		// Any pi/ctx call inside them must be stale-guarded.
		pendingResume = resumeAfterCompact(config, checkPoint);
		try {
			ctx.compact({
				onComplete: () => {
					// Resume is sent by the session_compact handler.
					try {
						if (ctx.hasUI) {
							ctx.ui.notify(
								pendingResume
									? "Auto-compaction completed; continuing"
									: "Auto-compaction completed",
								"info",
							);
						}
					} catch {
						// Stale ctx after session teardown; nothing left to notify.
					}
				},
				onError: (error) => {
					// Compact failed, but the agent was already aborted — still try to
					// resume so the interrupted run is not silently lost. No
					// session_compact event fires on failure, so send here, guarded:
					// if the session was disposed mid-compact the runtime is stale and
					// there is nothing to resume into.
					compacting = false;
					const resume = pendingResume;
					pendingResume = undefined;
					try {
						if (resume) pi.sendUserMessage(resume, { deliverAs: "followUp" });
						if (ctx.hasUI) ctx.ui.notify(`Auto-compaction failed: ${formatError(error)}`, "warning");
					} catch {
						// Stale ctx after session teardown; drop the resume.
					}
				},
			});
		} catch (error) {
			compacting = false;
			pendingResume = undefined;
			if (ctx.hasUI) ctx.ui.notify(`Auto-compaction failed: ${formatError(error)}`, "warning");
		}
	};

	pi.on("session_start", resetAttemptState);
	pi.on("session_shutdown", resetAttemptState);
	pi.on("session_compact", (event) => {
		// Only consume the pending resume for compactions this extension
		// triggered. Gate on our own in-flight `compacting` flag, NOT on
		// event.fromExtension: fromExtension is true when a
		// session_before_compact handler supplied the compaction content (e.g.
		// the Cursor provider's native summarizeAction) and false when pi's
		// built-in summarizer ran — either way this extension may have triggered
		// the compaction, so fromExtension is not a reliable signal here. Resume
		// still fires exactly once regardless of which summarizer produced the
		// content. willRetry means core overflow recovery already retries the
		// aborted turn; injecting a follow-up as well would double-resume.
		const triggeredHere = compacting;
		compacting = false;
		if (!triggeredHere || event.willRetry) return;
		const resume = pendingResume;
		pendingResume = undefined;
		if (resume) pi.sendUserMessage(resume, { deliverAs: "followUp" });
	});
	pi.on("turn_end", (_event, ctx) => maybeCompact("turn_end", ctx));
	pi.on("agent_end", (_event, ctx) => maybeCompact("agent_end", ctx));

	pi.registerCommand("auto-compact", {
		description: "Configure percent-based auto-compaction (config | status | reload)",
		getArgumentCompletions: (prefix) =>
			["config", "status", "reload"]
				.filter((value) => value.startsWith(prefix.toLowerCase()))
				.map((value) => ({ value, label: value })),
		handler: async (args, ctx) => {
			const action = args.trim().toLowerCase() || "config";
			if (action === "status") {
				ctx.ui.notify(`${describeConfig(config)}; ${configPath}`, "info");
				return;
			}
			if (action === "reload") {
				config = loadConfig(configPath);
				resetAttemptState();
				ctx.ui.notify(`${describeConfig(config)}; reloaded from ${configPath}`, "info");
				return;
			}
			if (action !== "config") {
				ctx.ui.notify("Usage: /auto-compact [config | status | reload]", "warning");
				return;
			}
			const next = await configure(ctx, config, configPath);
			if (next !== config) {
				config = next;
				resetAttemptState();
			}
		},
	});
}
