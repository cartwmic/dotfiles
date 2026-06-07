/**
 * goal-loop — a Claude-Code-style `/goal` for pi.
 *
 * Set a completion condition; after each agent turn a separate small "judge"
 * model evaluates it against the latest worker output. Not met → inject the
 * reason as a follow-up, starting another turn. Met → clear and notify. A hard
 * turn budget guarantees termination.
 *
 * Mechanism validated against the live pi runtime (see the change's design.md):
 *   - agent_end fires once per full agent run (correct evaluation point)
 *   - sendUserMessage(..., {deliverAs:"followUp"}) drives the next turn
 *   - a separate model resolves via modelRegistry + complete()
 *
 * Env:
 *   PI_GOAL_MAX_TURNS    hard turn budget (default 25)
 *   PI_GOAL_JUDGE_MODEL  "provider/model-id" override for the judge
 */
import { appendFileSync, existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";
import { complete } from "@mariozechner/pi-ai";
import {
	decideAfterEvaluation,
	isInterruptedStop,
	lastAssistantInfo,
	normalizeGoalConfig,
	parseGoalArg,
	parseVerdict,
	resolveSetting,
	type GoalConfig,
	type Verdict,
} from "./helpers.ts";

// Optional debug trace (set PI_GOAL_DEBUG=/path/to/log). No-op otherwise.
const DEBUG = process.env.PI_GOAL_DEBUG;
function dbg(line: string): void {
	if (DEBUG) {
		try {
			appendFileSync(DEBUG, `${Date.now()} ${line}\n`);
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

	async function judge(
		ctx: ExtensionContext,
		condition: string,
		transcript: string,
	): Promise<Verdict> {
		const resolved = await resolveJudge(ctx);
		if (!resolved) return { met: false, reason: "no judge model available/authenticated" };

		try {
			const res: any = await complete(
				resolved.model,
				{
					systemPrompt:
						"You are a strict completion evaluator. Given a GOAL and the latest worker output " +
						"(TRANSCRIPT), decide ONLY from what the transcript proves. Reply with a single JSON " +
						'object: {"met": boolean, "reason": string}. Set met=true only if the transcript ' +
						"demonstrably satisfies the goal. Keep reason to one sentence.",
					messages: [
						{
							role: "user",
							content: [
								{
									type: "text",
									text: `GOAL:\n${condition}\n\nTRANSCRIPT:\n${transcript || "(no worker output captured)"}`,
								},
							],
							timestamp: Date.now(),
						},
					],
				},
				{ apiKey: resolved.apiKey, headers: resolved.headers, maxTokens: 300, signal: ctx.signal },
			);
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
		description:
			"Autonomous completion loop — a small judge checks your condition after each turn until met",
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
		// User interrupted (or the turn errored): stop the loop instead of
		// re-injecting, otherwise the cancel fights an immediate new turn.
		if (isInterruptedStop(info.stopReason)) {
			const cond = goal.condition;
			clearGoal(ctx);
			dbg(`interrupted stopReason=${info.stopReason} — loop stopped`);
			ctx.ui.notify(`◎ Goal stopped (${info.stopReason}): ${cond}`, "warning");
			return;
		}

		const session = goal;
		session.evaluating = true;
		try {
			session.turns += 1;
			renderStatus(ctx);

			const verdict = await judge(ctx, session.condition, info.text);
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
}
