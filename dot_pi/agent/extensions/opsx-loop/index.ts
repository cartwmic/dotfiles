/**
 * opsx-loop — a guaranteed in-pi kickoff for the opsx drive-to-completion loop.
 *
 * `/opsx-loop <change>` injects a worker turn directed at the openspec-loop skill,
 * then after each agent turn runs `opsx-gate <change>` as the DETERMINISTIC judge:
 * exit 0 → done (ready to archive); non-zero → inject another turn carrying the
 * gate's failed-check report; bounded by a turn budget. This is the pi adapter for
 * the loop-continuation capability (ADR-0007); the generic `goal` extension is
 * never modified.
 *
 * Reuses the validated agent_end + sendUserMessage(followUp) mechanism
 * (ADR-0001/0004). Independent of the goal extension.
 */
import { spawn, spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";
import {
	buildModelEnv,
	LOOP_SUBCOMMANDS,
	parseLoopArg,
	parseLoopBudget,
	parseModelsJson,
	verdictFromExit,
	type LoopVerdict,
	type ResolvedModel,
} from "./helpers.ts";

const DEFAULT_BUDGET = 40;

interface LoopState {
	change: string;
	worktree?: string;
	turns: number;
	maxTurns: number;
	active: boolean;
	evaluating: boolean;
	lastReason?: string;
}

/** Resolve one role via the harness-neutral `opsx-models` CLI (consumer, not owner). */
function resolveModel(role: string, change: string): ResolvedModel | null {
	try {
		const r = spawnSync("opsx-models", [role, "--json", "--change", change], {
			encoding: "utf-8",
			timeout: 5000,
		});
		if (r.error || !r.stdout) return null;
		return parseModelsJson(r.stdout);
	} catch {
		return null;
	}
}

/**
 * Resolve the role models on loop start and EXPORT the OPSX_* vars into
 * process.env so the worker turns' subagent dispatch + authoring pick them up.
 * Consumer only: if `opsx-models` is absent the loop runs with vars unset
 * (pre-change behavior). Returns the names of the vars that were set.
 * (opsx-loop-kickoff.loop-exports-resolved-role-models)
 */
function exportModelEnv(change: string): string[] {
	const env = buildModelEnv({
		author: resolveModel("author", change),
		review: resolveModel("review", change),
		impl: resolveModel("impl", change),
		authorInSession: resolveModel("author-in-session", change),
	});
	for (const [k, v] of Object.entries(env)) process.env[k] = v;
	return Object.keys(env);
}

/** Read review.md for a change: returns its text or "" if absent. */
function readReview(change: string): string {
	try {
		const p = join(process.cwd(), "openspec", "changes", change, "review.md");
		return existsSync(p) ? readFileSync(p, "utf-8") : "";
	} catch {
		return "";
	}
}

/** Body field "**Name:** value" from review.md text. */
function bodyField(reviewMd: string, name: string): string | undefined {
	const m = reviewMd.match(new RegExp(`^\\*\\*${name}:\\*\\*\\s*(.+?)\\s*$`, "im"));
	const v = m?.[1]?.trim();
	return v && !v.startsWith("<") ? v : undefined;
}

/** Run opsx-gate as the judge. exit 0 = met. Never rejects (non-fatal on spawn error). */
function runGate(change: string, worktree: string | undefined, signal: AbortSignal): Promise<LoopVerdict> {
	const args = [change];
	if (worktree) args.push("--worktree", worktree);
	return new Promise((resolve) => {
		let out = "";
		try {
			const child = spawn("opsx-gate", args, { signal });
			child.stdout?.on("data", (d) => { out += String(d); });
			child.stderr?.on("data", (d) => { out += String(d); });
			child.on("error", (e: any) =>
				resolve({ met: false, reason: `opsx-gate failed to execute: ${e?.message ?? "unknown"}` }),
			);
			child.on("close", (code) => resolve(verdictFromExit(code, out)));
		} catch (e: any) {
			resolve({ met: false, reason: `opsx-gate failed to execute: ${e?.message ?? "unknown"}` });
		}
	});
}

export default function (pi: ExtensionAPI) {
	let loop: LoopState | undefined;

	function renderStatus(ctx: ExtensionContext): void {
		ctx.ui.setStatus(
			"opsx-loop",
			loop?.active ? `⟳ opsx-loop ${loop.change} · ${loop.turns}/${loop.maxTurns}` : undefined,
		);
	}

	function clearLoop(ctx: ExtensionContext): void {
		loop = undefined;
		renderStatus(ctx);
	}

	const workerDirective = (change: string, report?: string) =>
		`Use the openspec-loop skill to advance OpenSpec change "${change}" toward a green opsx-gate.\n` +
		`Run \`opsx-gate ${change}\` (with --worktree when applicable), fix the EARLIEST blocking ` +
		`GATE-FAIL line, delegate any review verdict to a blind subagent, and commit one unit of progress.` +
		(report ? `\n\nCurrent opsx-gate report:\n${report}` : "");

	pi.registerCommand("opsx-loop", {
		description: "Guaranteed opsx loop: /opsx-loop <change> | /opsx-loop status | /opsx-loop clear",
		getArgumentCompletions: (prefix: string) => {
			const p = prefix.trim().toLowerCase();
			return LOOP_SUBCOMMANDS.filter((s) => s.value.startsWith(p));
		},
		handler: async (args: string, ctx: ExtensionContext) => {
			const parsed = parseLoopArg(args ?? "");

			if (parsed.mode === "status") {
				if (!loop?.active) return "No active opsx-loop. Start one with: /opsx-loop <change>";
				return [
					`⟳ opsx-loop active — ${loop.turns}/${loop.maxTurns} turns`,
					`change: ${loop.change}`,
					`worktree: ${loop.worktree ?? "(same-tree)"}`,
					`last gate: ${loop.lastReason ?? "(pending first turn)"}`,
				].join("\n");
			}

			if (parsed.mode === "clear") {
				if (!loop?.active) return "No active opsx-loop to clear.";
				const c = loop.change;
				clearLoop(ctx);
				if (!ctx.isIdle()) ctx.abort();
				return `Cleared opsx-loop: ${c}`;
			}

			// set — replaces any active loop, resolves worktree + budget, starts work.
			const review = readReview(parsed.change);
			loop = {
				change: parsed.change,
				worktree: bodyField(review, "Worktree Path"),
				turns: 0,
				maxTurns: parseLoopBudget(review, DEFAULT_BUDGET),
				active: true,
				evaluating: false,
			};
			renderStatus(ctx);
			const exported = exportModelEnv(parsed.change);
			pi.sendUserMessage(workerDirective(parsed.change), { deliverAs: "followUp" });
			const modelNote = exported.length > 0 ? ` · models: ${exported.join(", ")}` : "";
			return `⟳ opsx-loop started (budget ${loop.maxTurns}) for ${parsed.change}${modelNote}`;
		},
	});

	pi.on("agent_end", async (event: any, ctx: ExtensionContext) => {
		if (!loop?.active || loop.evaluating) return; // inactive or re-entrant (clarify C1)

		// User interrupted / turn errored → stop instead of re-injecting.
		const last = (Array.isArray(event?.messages) ? event.messages : [])
			.slice()
			.reverse()
			.find((m: any) => m?.role === "assistant");
		const stopReason: string | undefined = typeof last?.stopReason === "string" ? last.stopReason : undefined;
		if (stopReason === "aborted" || stopReason === "error") {
			const c = loop.change;
			clearLoop(ctx);
			ctx.ui.notify(`⟳ opsx-loop stopped (${stopReason}): ${c}`, "warning");
			return;
		}

		const session = loop;
		session.evaluating = true;
		try {
			session.turns += 1;
			renderStatus(ctx);

			const verdict = await runGate(session.change, session.worktree, ctx.signal);
			if (loop !== session || !session.active) return; // cleared during async gate run
			session.lastReason = verdict.reason;

			if (verdict.met) {
				const c = session.change;
				clearLoop(ctx);
				ctx.ui.notify(`⟳ opsx-loop: ${c} — gate green. Ready to archive.`, "info");
				return;
			}
			if (session.turns >= session.maxTurns) {
				const c = session.change;
				clearLoop(ctx);
				ctx.ui.notify(`⟳ opsx-loop: budget ${session.maxTurns} exhausted for ${c}; worktree preserved.`, "warning");
				return;
			}
			pi.sendUserMessage(workerDirective(session.change, verdict.reason), { deliverAs: "followUp" });
		} finally {
			session.evaluating = false;
		}
	});
}
