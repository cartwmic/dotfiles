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
import { AUTO_COMPACT_WILL_RESUME_EVENT } from "./events.ts";

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
			const selected = await ctx.ui.select("After inter-turn compaction (turn_end)", [
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

export interface AutoCompactExtensionOptions {
	/** Test/deployment override; runtime reload still reads configPath. */
	config?: AutoCompactConfig;
	configPath?: string;
}

export function registerAutoCompactExtension(
	pi: ExtensionAPI,
	options: AutoCompactExtensionOptions = {},
): void {
	const configPath = options.configPath ?? join(extensionDir(), "config.json");
	let config = options.config ?? loadConfig(configPath);
	let compacting = false;
	let lastAttemptTokens: number | undefined;
	let pendingResume: string | undefined;
	let pendingTurnEndCheck = false;
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
		pendingTurnEndCheck = false;
		consecutiveIneffective = 0;
		autoDisabledForSession = false;
	};

	const maybeCompact = (
		checkPoint: CheckPoint,
		ctx: ExtensionContext,
		agentWillContinue: boolean,
	): void => {
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

		// ctx.compact() aborts the active agent first. After inter-turn compaction,
		// re-inject so the interrupted run can continue. Skip final-turn and
		// agent_end compactions: the run already finished and a follow-up would
		// spuriously start new work.
		//
		// Resume only from onComplete. Pi emits session_compact while its
		// compaction controller is still active, so sendUserMessage there is rejected
		// with "Cannot submit a prompt while compaction is in progress." onComplete
		// runs after compact() returns and clears that controller. Callbacks can also
		// fire after session disposal, so every pi/ctx action remains stale-guarded.
		pendingResume = resumeAfterCompact(config, checkPoint, agentWillContinue);
		if (pendingResume) {
			// Pi 0.84+ preserves agent_end/agent_settled while compact() aborts the
			// active run. Tell cooperating extensions this abort is internal and a
			// follow-up will resume it, so they do not treat it as a user interrupt.
			pi.events?.emit(AUTO_COMPACT_WILL_RESUME_EVENT, undefined);
		}
		try {
			ctx.compact({
				onComplete: () => {
					compacting = false;
					const resume = pendingResume;
					pendingResume = undefined;
					try {
						if (resume) pi.sendUserMessage(resume, { deliverAs: "followUp" });
						if (ctx.hasUI) {
							ctx.ui.notify(
								resume ? "Auto-compaction completed; continuing" : "Auto-compaction completed",
								"info",
							);
						}
					} catch {
						// Stale ctx after session teardown; nothing left to resume or notify.
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
		// session_compact precedes onComplete. Never submit from here: Pi still
		// rejects prompts while its compaction controller is active. Only cancel a
		// pending follow-up if core says it will retry the interrupted run itself.
		if (compacting && event.willRetry) pendingResume = undefined;
	});
	// A final turn_end is immediately followed by agent_end, while an inter-turn
	// turn_end is followed by turn_start. Defer the turn-end check until that
	// next turn actually starts so only an agent run that still has work is
	// aborted and resumed. Checking directly in turn_end cannot distinguish the
	// final response and would spuriously start a new run after compaction.
	pi.on("turn_end", () => {
		pendingTurnEndCheck = true;
	});
	pi.on("turn_start", (_event, ctx) => {
		if (!pendingTurnEndCheck) return;
		pendingTurnEndCheck = false;
		maybeCompact("turn_end", ctx, true);
	});
	// The "agent_end" checkpoint is evaluated at agent_settled, not agent_end.
	// agent_end is a low-level attempt boundary: Pi may still run a native retry,
	// overflow recovery, or a continuation queued by another extension's agent_end
	// handler (e.g. the goal loop's follow-up). agent_settled fires only once that
	// automatic work is exhausted, so final-run compaction cannot preempt it.
	pi.on("agent_settled", (_event, ctx) => {
		if (pendingTurnEndCheck) {
			pendingTurnEndCheck = false;
			maybeCompact("turn_end", ctx, false);
		}
		maybeCompact("agent_end", ctx, false);
	});

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

export default function (pi: ExtensionAPI): void {
	registerAutoCompactExtension(pi);
}
