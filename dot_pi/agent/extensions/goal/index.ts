/**
 * goal-loop — a Claude-Code-style `/goal` for pi.
 *
 * Set a completion condition; after each agent turn a separate small "judge"
 * model evaluates it against the latest worker output. Not met → inject the
 * reason as a follow-up, starting another turn. Met → clear and notify. A hard
 * turn budget guarantees termination.
 *
 * Mechanism validated against the live pi runtime (see the change's design.md):
 *   - agent_end is a low-level attempt boundary: clean ends evaluate; error defers
 *   - agent_settled stops only when an error remains unresolved after Pi settles
 *   - sendUserMessage(..., {deliverAs:"followUp"}) drives the next turn
 *   - a separate model resolves via modelRegistry + complete()
 *
 * Env:
 *   PI_GOAL_MAX_TURNS    hard turn budget (default 25)
 *   PI_GOAL_JUDGE_MODEL  "provider/model-id" override for the model judge
 *   PI_GOAL_JUDGE_CMD    shell command judge; exit 0 = met (overrides the model
 *                        judge). The command may inspect filesystem/git state
 *                        outside the transcript; GOAL_CONDITION is exported to it.
 *   PI_GOAL_DEBUG        debug trace path (default ~/.pi/goal-debug.log; "0"/"off"
 *                        disables). Rotates at 5MB keeping one .1 generation.
 */
import { spawn } from "node:child_process";
import { appendFileSync, existsSync, readFileSync, renameSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";
import { complete, type Tool } from "@mariozechner/pi-ai";
import { Type } from "@sinclair/typebox";
import {
	decideAfterEvaluation,
	decideAgentEndBoundary,
	GOAL_SUBCOMMANDS,
	lastAssistantInfo,
	commandVerdict,
	normalizeGoalConfig,
	parseGoalArg,
	parseVerdict,
	resolveSetting,
	verdictFromToolArgs,
	type GoalConfig,
	type Verdict,
} from "./helpers.ts";

/**
 * Run a command judge: exit 0 = met, non-zero / spawn failure = not met with the
 * command's combined output as the reason. The command may inspect filesystem and
 * git state outside the transcript (goal-loop.pluggable-command-judge,
 * goal-loop.judge-each-completed-turn). Never rejects.
 */
function runCommandJudge(command: string, condition: string, signal: AbortSignal): Promise<Verdict> {
	return new Promise((resolve) => {
		let out = "";
		try {
			const child = spawn(command, {
				shell: true,
				signal,
				env: { ...process.env, GOAL_CONDITION: condition },
			});
			child.stdout?.on("data", (d) => { out += String(d); });
			child.stderr?.on("data", (d) => { out += String(d); });
			child.on("error", (e: any) =>
				resolve({ met: false, reason: `judge command failed to execute: ${e?.message ?? "unknown"}` }),
			);
			child.on("close", (code) => resolve(commandVerdict(code, out)));
		} catch (e: any) {
			resolve({ met: false, reason: `judge command failed to execute: ${e?.message ?? "unknown"}` });
		}
	});
}

// Structured-output "capture" path: the judge calls this tool instead of
// emitting free text. Reliable across providers incl. the claude-bridge CLI.
const SUBMIT_VERDICT: Tool = {
	name: "submit_verdict",
	description: "Submit the completion verdict for the GOAL. Call this exactly once.",
	parameters: Type.Object({
		met: Type.Boolean({ description: "true only if the TRANSCRIPT demonstrably satisfies the GOAL" }),
		reason: Type.String({ maxLength: 300, description: "one-sentence justification" }),
	}),
};

// Debug trace — on by default at ~/.pi/goal-debug.log.
// PI_GOAL_DEBUG=/path/to/log overrides the path; PI_GOAL_DEBUG=0|off disables.
// Rotates at 5MB by renaming to <path>.1 (one generation kept, ~10MB worst case).
const DEBUG = resolveDebugPath(process.env.PI_GOAL_DEBUG);
const DEBUG_MAX_BYTES = 5 * 1024 * 1024;
function resolveDebugPath(env: string | undefined): string | undefined {
	const v = (env ?? "").trim();
	if (v === "0" || v.toLowerCase() === "off" || v.toLowerCase() === "false") return undefined;
	if (v.length > 0) return v;
	return join(homedir(), ".pi", "goal-debug.log");
}
function dbg(line: string): void {
	if (DEBUG) {
		try {
			if (existsSync(DEBUG) && statSync(DEBUG).size >= DEBUG_MAX_BYTES) {
				renameSync(DEBUG, `${DEBUG}.1`); // overwrites previous generation
			}
			appendFileSync(DEBUG, `${new Date().toISOString()} ${line}\n`);
		} catch {
			/* ignore */
		}
	}
}

interface GoalState {
	condition: string;
	turns: number;
	maxTurns: number;
	active: boolean;
	lastReason?: string;
	evaluating: boolean;
	/** Errored low-level attempt awaiting Pi's final agent_settled signal. */
	pendingError?: boolean;
}

const DEFAULT_MAX_TURNS = 25;
// Small/cheap judge preference, tried in order; falls back to the session model.
// Used only when no judge model is set via config.json or PI_GOAL_JUDGE_MODEL.
const JUDGE_PREFERENCE: ReadonlyArray<readonly [string, string]> = [
	["anthropic", "claude-haiku-4-5"],
	["deepseek", "deepseek-v4-flash"],
];

// Settings, lowest-to-highest precedence: built-in default < config.json < env var.
// config.json is co-located with this file (deployed to ~/.pi/agent/extensions/goal/).
function loadConfig(): GoalConfig {
	try {
		const path = join(dirname(fileURLToPath(import.meta.url)), "config.json");
		if (!existsSync(path)) return {};
		return normalizeGoalConfig(JSON.parse(readFileSync(path, "utf-8")));
	} catch {
		return {};
	}
}

function parsePositiveInt(s: string): number | undefined {
	const n = Number.parseInt(s, 10);
	return Number.isFinite(n) && n > 0 ? n : undefined;
}

export default function (pi: ExtensionAPI) {
	// Long-lived closure state. NEVER capture `ctx` here (it goes stale across
	// session switch/fork/reload — design D5); use the per-call ctx instead.
	let goal: GoalState | undefined;
	const config = loadConfig();

	// env PI_GOAL_MAX_TURNS > config.maxTurns > built-in default (goal-loop.configurable-judge-and-budget)
	function resolveMaxTurns(): number {
		return resolveSetting(process.env.PI_GOAL_MAX_TURNS, parsePositiveInt, config.maxTurns, DEFAULT_MAX_TURNS);
	}

	// env PI_GOAL_JUDGE_MODEL > config.judgeModel > (preference list, handled in resolveJudge)
	function configuredJudgeSpec(): string | undefined {
		return resolveSetting<string | undefined>(
			process.env.PI_GOAL_JUDGE_MODEL,
			(s) => s,
			config.judgeModel,
			undefined,
		);
	}

	// env PI_GOAL_JUDGE_CMD > config.judgeCommand > none. When set, the command
	// judge replaces the model judge (goal-loop.pluggable-command-judge).
	function configuredJudgeCommand(): string | undefined {
		return resolveSetting<string | undefined>(
			process.env.PI_GOAL_JUDGE_CMD,
			(s) => s,
			config.judgeCommand,
			undefined,
		);
	}

	function renderStatus(ctx: ExtensionContext): void {
		ctx.ui.setStatus(
			"goal",
			goal?.active ? `◎ goal · ${goal.turns}/${goal.maxTurns}` : undefined,
		);
	}

	function clearGoal(ctx: ExtensionContext): void {
		goal = undefined;
		renderStatus(ctx);
	}

	async function resolveJudge(
		ctx: ExtensionContext,
	): Promise<{ model: any; apiKey?: string; headers?: Record<string, string> } | undefined> {
		const candidates: any[] = [];
		const spec = configuredJudgeSpec();
		if (spec) {
			const slash = spec.indexOf("/");
			if (slash > 0) {
				const m = ctx.modelRegistry.find(spec.slice(0, slash), spec.slice(slash + 1));
				if (m) candidates.push(m);
			}
		}
		for (const [provider, id] of JUDGE_PREFERENCE) {
			const m = ctx.modelRegistry.find(provider, id);
			if (m) candidates.push(m);
		}
		if (ctx.model) candidates.push(ctx.model);

		for (const model of candidates) {
			const auth = await ctx.modelRegistry.getApiKeyAndHeaders(model);
			if (auth.ok) return { model, apiKey: auth.apiKey, headers: auth.headers };
		}
		return undefined;
	}

	// Latest worker turn's surfaced text (fallback to the session entries when
	// the agent_end event carries no assistant text). Bounded — clarify A1 / D7.
	function extractTranscript(ctx: ExtensionContext): string {
		const entries = ctx.sessionManager.getEntries() as any[];
		for (let i = entries.length - 1; i >= 0; i--) {
			const msg = entries[i]?.message ?? entries[i];
			if (msg?.role === "assistant" && Array.isArray(msg.content)) {
				return msg.content
					.filter((c: any) => c?.type === "text")
					.map((c: any) => c.text)
					.join("\n")
					.trim();
			}
		}
		return "";
	}

	async function judge(
		ctx: ExtensionContext,
		condition: string,
		transcript: string,
	): Promise<Verdict> {
		// Command judge takes precedence: deterministic, evaluates external state.
		const judgeCmd = configuredJudgeCommand();
		if (judgeCmd) return runCommandJudge(judgeCmd, condition, ctx.signal);

		const resolved = await resolveJudge(ctx);
		if (!resolved) return { met: false, reason: "no judge model available/authenticated" };

		// Instruction in the USER message (some providers, e.g. the claude-bridge
		// CLI, ignore systemPrompt). Ask for a structured tool call; fall back to
		// free-text JSON parsing if the model emits text instead of a tool call.
		const prompt =
			"You are a strict completion evaluator. Decide ONLY from the TRANSCRIPT whether the GOAL is " +
			"satisfied, then call submit_verdict exactly once. Set met=true only if the transcript " +
			`demonstrably satisfies the goal.\n\nGOAL:\n${condition}\n\nTRANSCRIPT:\n${transcript || "(no worker output captured)"}`;
		try {
			const res: any = await complete(
				resolved.model,
				{
					messages: [{ role: "user", content: [{ type: "text", text: prompt }], timestamp: Date.now() }],
					tools: [SUBMIT_VERDICT],
				},
				{ apiKey: resolved.apiKey, headers: resolved.headers, maxTokens: 300, signal: ctx.signal },
			);
			const toolCall = (res?.content ?? []).find(
				(c: any) => c?.type === "toolCall" && c.name === "submit_verdict",
			);
			const fromTool = toolCall && verdictFromToolArgs(toolCall.arguments);
			if (fromTool) return fromTool;
			// Fallback: free-text JSON.
			const text = (res?.content ?? [])
				.filter((c: any) => c?.type === "text")
				.map((c: any) => c.text)
				.join("");
			return parseVerdict(text);
		} catch (e: any) {
			return { met: false, reason: `evaluator error: ${e?.message ?? "unknown"}` };
		}
	}

	pi.registerCommand("goal", {
		description: "Autonomous loop: /goal <condition> | /goal status | /goal clear",
		getArgumentCompletions: (prefix: string) => {
			const p = prefix.trim().toLowerCase();
			return GOAL_SUBCOMMANDS.filter((s) => s.value.startsWith(p));
		},
		handler: async (args: string, ctx: ExtensionContext) => {
			const parsed = parseGoalArg(args ?? "");

			if (parsed.mode === "status") {
				if (!goal?.active) {
					return "No active goal. Set one with: /goal <completion condition provable from your output>";
				}
				return [
					`◎ goal active — ${goal.turns}/${goal.maxTurns} turns`,
					`condition: ${goal.condition}`,
					`last evaluation: ${goal.lastReason ?? "(pending first turn)"}`,
				].join("\n");
			}

			if (parsed.mode === "clear") {
				if (!goal?.active) return "No active goal to clear.";
				const cond = goal.condition;
				clearGoal(ctx);
				// Also stop any in-flight turn so a running loop halts immediately.
				if (!ctx.isIdle()) ctx.abort();
				return `Cleared goal: ${cond}`;
			}

			// set — replaces any active goal and starts working immediately.
			goal = {
				condition: parsed.condition,
				turns: 0,
				maxTurns: resolveMaxTurns(),
				active: true,
				evaluating: false,
			};
			renderStatus(ctx);
			// Always triggers a turn; deliverAs only matters when mid-stream
			// (queue as follow-up — clarify C1).
			pi.sendUserMessage(
				`Work toward this goal until it is met: ${parsed.condition}\n\n` +
					"When you believe it is satisfied, state clearly how your output proves it.",
				{ deliverAs: "followUp" },
			);
			dbg(`set condition="${parsed.condition}" maxTurns=${goal.maxTurns}`);
			return `◎ Goal set (budget ${goal.maxTurns} turns): ${parsed.condition}`;
		},
	});

	pi.on("agent_end", async (event: any, ctx: ExtensionContext) => {
		if (!goal?.active || goal.evaluating) return; // inactive (clarify C3) or re-entrant (D4)

		const info = lastAssistantInfo(event?.messages);
		const boundary = decideAgentEndBoundary(info.stopReason);

		// Explicit user abort remains immediately terminal. It must never wait for or
		// be undone by a later settlement signal.
		if (boundary === "stop") {
			const cond = goal.condition;
			clearGoal(ctx);
			dbg(`interrupted stopReason=${info.stopReason} — loop stopped`);
			ctx.ui.notify(`◎ Goal stopped (${info.stopReason}): ${cond}`, "warning");
			return;
		}

		// agent_end is a low-level attempt boundary: Pi decides native retry,
		// compaction/retry, and queued continuation only after extension handlers run.
		// Preserve the exact goal object and defer terminal policy to agent_settled.
		if (boundary === "defer") {
			goal.pendingError = true;
			dbg("error stopReason — deferring to agent_settled (preserving goal)");
			return;
		}

		// A clean native continuation supersedes any prior errored attempt and follows
		// the existing judge/continuation path exactly once.
		goal.pendingError = undefined;

		const session = goal;
		session.evaluating = true;
		try {
			session.turns += 1;
			renderStatus(ctx);

			const verdict = await judge(ctx, session.condition, info.text || extractTranscript(ctx));
			dbg(`turn ${session.turns}/${session.maxTurns} met=${verdict.met} reason="${verdict.reason}"`);

			// Goal may have been cleared or replaced during the async judge call.
			if (goal !== session || !session.active) return;
			session.lastReason = verdict.reason;

			const action = decideAfterEvaluation(session, verdict);
			if (action === "achieved") {
				const cond = session.condition;
				clearGoal(ctx);
				ctx.ui.notify(`◎ Goal achieved: ${cond} — ${verdict.reason}`, "info");
				return;
			}

			if (action === "exhausted") {
				const cond = session.condition;
				const max = session.maxTurns;
				clearGoal(ctx);
				ctx.ui.notify(
					`◎ Goal stopped (budget ${max} turns exhausted): ${cond} — last: ${verdict.reason}`,
					"warning",
				);
				return;
			}

			renderStatus(ctx);
			pi.sendUserMessage(
				`[goal not yet met] ${verdict.reason}\nKeep working toward: ${session.condition}`,
				{ deliverAs: "followUp" },
			);
		} finally {
			session.evaluating = false;
		}
	});

	pi.on("agent_settled", async (_event: any, ctx: ExtensionContext) => {
		const session = goal;
		if (!session?.active || !session.pendingError || session.evaluating) return;
		// Another extension may start a new run from an earlier agent_settled handler.
		// In that case preserve the pending outcome; its eventual clean/error boundary
		// will supersede or settle it without racing that continuation.
		if (typeof ctx.isIdle === "function" && !ctx.isIdle()) return;

		// Consume before any further work so clear/replacement makes a stale settled a no-op.
		session.pendingError = undefined;
		const cond = session.condition;
		clearGoal(ctx);
		dbg("settled with unresolved error — loop stopped");
		ctx.ui.notify(`◎ Goal stopped (error): ${cond}`, "warning");
	});
}
