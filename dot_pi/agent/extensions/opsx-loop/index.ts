/**
 * opsx-loop — a guaranteed in-pi kickoff for the opsx drive-to-completion loop.
 *
 * `/opsx-loop <change>` injects a worker turn directed at the openspec-loop skill,
 * then after each agent turn runs `opsx gate <change>` as the DETERMINISTIC judge:
 * exit 0 → done (ready to archive); non-zero → inject another turn carrying the
 * gate's failed-check report; bounded by a turn budget. This is the pi adapter for
 * the loop-continuation capability (ADR-0007); the generic `goal` extension is
 * never modified.
 *
 * Reuses the validated agent_end + sendUserMessage(followUp) mechanism
 * (ADR-0001/0004). Independent of the goal extension.
 */
import { spawn, spawnSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";
import {
	buildModelEnv,
	classifyDoneness,
	donenessRatchet,
	gateFailKey,
	hashDir,
	LOOP_SUBCOMMANDS,
	OPSX_MODEL_ENV_KEYS,
	parseDonenessGaps,
	parseLoopArg,
	parseLoopBudget,
	parseModelsJson,
	verdictFromExit,
	type LoopVerdict,
	type ResolvedModel,
} from "./helpers.ts";

const STALL_LIMIT = 3; // consecutive identical no-progress gate failures → stop

interface LoopState {
	// `change` is undefined while a goal/conversation loop is still distilling its
	// intent into a new change dir; `awaitingChange` guards that pre-gate phase.
	change?: string;
	goal?: string; // goal text (undefined = conversation-driven); only set in goal mode
	awaitingChange: boolean;
	preChangeDirs?: string[]; // snapshot of change-dir names at kickoff (goal mode)
	worktree?: string;
	turns: number;
	maxTurns?: number; // undefined = unbounded (no budget) unless configured
	active: boolean;
	evaluating: boolean;
	lastReason?: string;
	stallKey?: string;
	stallCount: number;
	lastProgress?: string;
	// Snapshot of change-dir names from the previous distilling turn; an unchanged
	// set advances the distill stall counter (no new change is being created).
	lastDirs?: string[];
	// Running-minimum gap set for the current doneness-blocked streak (undefined
	// outside that state). The doneness stall signal ratchets against this, not
	// against change-dir content, so file churn without gap closure trips the stall.
	minGaps?: string[];
}

/** Active (non-archive) change-dir names under a repo's openspec/changes. */
function listChangeDirs(cwd: string): string[] {
	try {
		const base = join(cwd, "openspec", "changes");
		return readdirSync(base, { withFileTypes: true })
			.filter((e) => e.isDirectory() && e.name !== "archive")
			.map((e) => e.name);
	} catch {
		return [];
	}
}

/**
 * A change dir created since the kickoff snapshot that already carries a frozen
 * intent.md (the openspec-loop precondition). If several qualify, the one whose
 * intent.md was most recently written wins. undefined until one appears.
 * (opsx-loop-kickoff.goal-and-conversation-kickoff)
 */
function detectNewChange(pre: string[], cwd: string): string | undefined {
	const preSet = new Set(pre);
	const base = join(cwd, "openspec", "changes");
	const ready = listChangeDirs(cwd)
		.filter((n) => !preSet.has(n) && existsSync(join(base, n, "intent.md")));
	if (ready.length === 0) return undefined;
	const mtime = (n: string): number => {
		try {
			return statSync(join(base, n, "intent.md")).mtimeMs;
		} catch {
			return 0;
		}
	};
	return ready.sort((a, b) => mtime(b) - mtime(a))[0];
}

/** Resolve one role via the harness-neutral `opsx models` CLI (consumer, not owner). */
function resolveModel(role: string, change: string, cwd: string): ResolvedModel | null {
	try {
		const r = spawnSync("opsx", ["models", role, "--json", "--change", change], {
			encoding: "utf-8",
			timeout: 5000,
			cwd,
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
 * Consumer only: if `opsx models` is absent the loop runs with vars unset
 * (pre-change behavior). Returns the names of the vars that were set.
 * (opsx-loop-kickoff.loop-exports-resolved-role-models)
 */
function exportModelEnv(change: string, cwd: string): string[] {
	const env = buildModelEnv({
		author: resolveModel("author", change, cwd),
		review: resolveModel("review", change, cwd),
		impl: resolveModel("impl", change, cwd),
		authorInSession: resolveModel("author-in-session", change, cwd),
	});
	// Clear ALL role keys first: a prior loop's exports must not leak into this
	// change (stale env is the highest-precedence resolver layer and would both
	// misroute models and force author-marker enforcement on unrelated changes).
	for (const k of OPSX_MODEL_ENV_KEYS) delete process.env[k];
	for (const [k, v] of Object.entries(env)) process.env[k] = v;
	return Object.keys(env);
}

/** Read review.md for a change: returns its text or "" if absent. */
function readReview(change: string, cwd: string): string {
	try {
		const p = join(cwd, "openspec", "changes", change, "review.md");
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

/**
 * Hard ceiling on one `opsx gate` run. The gate itself bounds each validator
 * (OPSX_GATE_CMD_TIMEOUT, default 600s); this is the outer belt-and-suspenders
 * bound so a wedged gate process can never leave the loop stuck in
 * `evaluating=true` forever (budget/stall guards only run AFTER the gate
 * returns). Override with OPSX_GATE_TIMEOUT_MS.
 */
function gateTimeoutMs(): number {
	const raw = process.env.OPSX_GATE_TIMEOUT_MS;
	if (raw && /^\d+$/.test(raw)) {
		const n = Number.parseInt(raw, 10);
		if (n > 0) return n;
	}
	return 15 * 60 * 1000; // 15 min: > the gate's own 600s per-validator bound
}

/** Run opsx gate as the judge. exit 0 = met. Never rejects (non-fatal on spawn error/timeout). */
function runGate(change: string, worktree: string | undefined, signal: AbortSignal, cwd: string): Promise<LoopVerdict> {
	const args = ["gate", change];
	if (worktree) args.push("--worktree", worktree);
	return new Promise((resolve) => {
		let out = "";
		let timedOut = false;
		try {
			const child = spawn("opsx", args, { signal, cwd });
			const ms = gateTimeoutMs();
			const timer = setTimeout(() => {
				timedOut = true;
				try {
					child.kill("SIGKILL");
				} catch {
					/* already gone */
				}
			}, ms);
			child.stdout?.on("data", (d) => { out += String(d); });
			child.stderr?.on("data", (d) => { out += String(d); });
			child.on("error", (e: any) => {
				clearTimeout(timer);
				resolve({ met: false, reason: `opsx gate failed to execute: ${e?.message ?? "unknown"}` });
			});
			child.on("close", (code) => {
				clearTimeout(timer);
				if (timedOut) {
					resolve({ met: false, reason: `GATE-FAIL timeout 1 opsx gate exceeded ${ms}ms and was killed` });
					return;
				}
				resolve(verdictFromExit(code, out));
			});
		} catch (e: any) {
			resolve({ met: false, reason: `opsx gate failed to execute: ${e?.message ?? "unknown"}` });
		}
	});
}

/** Re-resolve a usable worktree path from the change's review.md, or undefined. */
function resolveWorktree(change: string, cwd: string): string | undefined {
	const wt = bodyField(readReview(change, cwd), "Worktree Path");
	if (!wt) return undefined;
	try {
		const r = spawnSync("git", ["-C", wt, "rev-parse", "--is-inside-work-tree"], { encoding: "utf-8", timeout: 5000 });
		return r.status === 0 ? wt : undefined; // blank/stale path → no --worktree
	} catch {
		return undefined;
	}
}

/**
 * A token capturing observable progress: worktree HEAD + dirty status of the
 * change dir. A change in either between evaluations resets the stall counter
 * (committed OR uncommitted in-place authoring counts as progress).
 * (opsx-loop-kickoff.stall-detection-stops-the-loop)
 */
function progressToken(change: string, worktree: string | undefined, cwd: string): string {
	const dir = worktree ?? cwd;
	let head = "";
	try {
		head = spawnSync("git", ["-C", dir, "rev-parse", "HEAD"], { encoding: "utf-8", timeout: 5000 }).stdout?.trim() ?? "";
	} catch {
		/* not a git tree / no HEAD: rely on the content digest alone */
	}
	// Content digest of ALL files under the change dir captures committed, staged,
	// unstaged, AND untracked edits uniformly (git index state is irrelevant).
	const content = hashDir(join(dir, "openspec", "changes", change));
	return `${head}\n${content}`;
}

/**
 * Read the change's doneness.md (from the located worktree, else cwd) and classify
 * it for stall routing: its state (`satisfied` → ordinary signal; `gap` → the
 * bounded gap-set ratchet) and its normalized gap set. An absent/unreadable file
 * is the empty-set `gap` sentinel. The extension parses doneness.md DIRECTLY (never
 * the gate's free-text message). (opsx-loop-kickoff.stall-detection-stops-the-loop)
 */
function readDoneness(
	change: string,
	worktree: string | undefined,
	cwd: string,
): { state: "satisfied" | "gap"; gaps: string[] } {
	const dir = worktree ?? cwd;
	const fp = join(dir, "openspec", "changes", change, "doneness.md");
	let md: string | null = null;
	try {
		if (existsSync(fp)) md = readFileSync(fp, "utf-8");
	} catch {
		/* unreadable → treated as the empty-set gap sentinel */
	}
	return { state: classifyDoneness(md), gaps: md == null ? [] : parseDonenessGaps(md) };
}

/**
 * Run `opsx models <args>` synchronously with cwd = the session dir; returns
 * combined output. OPSX_ROOT is deliberately NOT forced: `opsx models` walks
 * ancestors of cwd to find the repo's openspec/, which works from any
 * subdirectory (forcing OPSX_ROOT=cwd broke `--layer project` when the pi
 * session cwd was not the repo root).
 */
function runModels(args: string[], cwd: string): { code: number; out: string } {
	try {
		const env = { ...process.env };
		delete env.OPSX_ROOT;
		const r = spawnSync("opsx", ["models", ...args], { encoding: "utf-8", timeout: 10000, cwd, env });
		if (r.error) return { code: 1, out: `opsx models failed to execute: ${r.error.message}` };
		return { code: r.status ?? 1, out: `${r.stdout ?? ""}${r.stderr ?? ""}`.trim() };
	} catch (e: any) {
		return { code: 1, out: `opsx models failed to execute: ${e?.message ?? "unknown"}` };
	}
}

export default function (pi: ExtensionAPI) {
	let loop: LoopState | undefined;

	function renderStatus(ctx: ExtensionContext): void {
		const label = loop?.change ?? (loop?.goal ? "(distilling goal)" : "(distilling)");
		ctx.ui.setStatus(
			"opsx-loop",
			loop?.active ? `⟳ opsx-loop ${label} · ${loop.turns}/${loop.maxTurns ?? "∞"}` : undefined,
		);
	}

	function clearLoop(ctx: ExtensionContext): void {
		loop = undefined;
		renderStatus(ctx);
	}

	// Appended to every injected loop directive. This is an AUTONOMOUS drive-to-green
	// loop: pausing to ask the user defeats the purpose, so suppress clarifying
	// questions except when genuinely blocked.
	const AUTONOMY =
		`\n\nThis is an autonomous drive-to-green loop. Do NOT pause to ask the user ` +
		`questions (do not use the ask-user / clarifying-question tool) or wait for ` +
		`confirmation. Make the most reasonable decision from the intent, specs, and ` +
		`conversation, record any assumption in the change artifacts, and keep going. ` +
		`ONLY stop to ask if you are truly blocked — genuinely ambiguous intent that ` +
		`cannot be inferred, or an irreversible/destructive action outside this change ` +
		`(e.g. deploy, force-push, data loss). The opsx gate is the arbiter of done, ` +
		`not the user.`;

	// Two forms, mirroring the goal extension's proven split: a rich KICKOFF sent
	// once when a change is adopted (report omitted), and a terse CONTINUATION nudge
	// on every subsequent turn (report present) that just says "keep going, fix this"
	// — never re-issuing the task setup, which is what made re-injects read as a new
	// request.
	const workerDirective = (change: string, report?: string) =>
		report === undefined
			? // KICKOFF — first turn on this change.
				`Use the openspec-loop skill to drive OpenSpec change "${change}" to a green opsx gate. ` +
				`Run \`opsx gate ${change}\` (with --worktree when applicable), fix the EARLIEST blocking ` +
				`GATE-FAIL line, delegate any review verdict to a blind subagent, and commit one unit of progress.` +
				AUTONOMY
			: // CONTINUATION — terse nudge; the change is already in progress.
				`[opsx gate still red] "${change}" is not done yet. Keep advancing the SAME in-progress ` +
				`change: fix the EARLIEST blocking GATE-FAIL below and commit one unit of progress.\n\n${report}` +
				AUTONOMY;

	// Goal/conversation kickoff: establish a frozen intent.md (reuse an existing one
	// or distill goal/conversation into a NEW change), then hand off to the loop.
	const distillDirective = (goal?: string) =>
		`Start a new OpenSpec change and drive the FULL workflow to a green opsx gate using the openspec-loop skill.\n\n` +
		`Step 1 — establish the frozen intent:\n` +
		`- If an active change with a frozen intent.md already captures this work, use it as-is.\n` +
		(goal
			? `- Otherwise distill this goal into a new change: "${goal}".`
			: `- Otherwise distill our current conversation — the intent we have converged on — into a new change.`) +
		` Use openspec-explore / openspec-propose to create openspec/changes/<name>/ with a frozen intent.md.\n` +
		`Step 2 — run the openspec-loop skill against that change: advance propose→apply behind ` +
		"`opsx gate <name>`, fixing the EARLIEST blocking GATE-FAIL each turn, delegating review " +
		`verdicts to blind subagents, and committing one unit of progress per turn.\n` +
		`Announce the new change name as soon as its intent.md is frozen.` +
		AUTONOMY;

	pi.registerCommand("opsx-loop", {
		description: "Guaranteed opsx loop: /opsx-loop goal [text] | <change> | status | clear | models",
		getArgumentCompletions: (prefix: string) => {
			const p = prefix.trim().toLowerCase();
			return LOOP_SUBCOMMANDS.filter((s) => s.value.startsWith(p));
		},
		handler: async (args: string, ctx: ExtensionContext) => {
			const parsed = parseLoopArg(args ?? "");

			if (parsed.mode === "status") {
				if (!loop?.active) {
					ctx.ui.notify("No active opsx-loop. Start one with: /opsx-loop goal [text] | /opsx-loop <change>", "info");
					return;
				}
				const changeLine = loop.change
					? `change: ${loop.change}`
					: `change: (distilling ${loop.goal ? `goal: ${loop.goal}` : "conversation"} → intent.md)`;
				ctx.ui.notify([
					`⟳ opsx-loop active — ${loop.turns}/${loop.maxTurns ?? "∞"} turns`,
					changeLine,
					`worktree: ${loop.worktree ?? "(same-tree)"}`,
					`last gate: ${loop.lastReason ?? "(pending first turn)"}`,
				].join("\n"), "info");
				return;
			}

			if (parsed.mode === "clear") {
				if (!loop?.active) {
					ctx.ui.notify("No active opsx-loop to clear.", "info");
					return;
				}
				const c = loop.change ?? (loop.goal ? `goal "${loop.goal}"` : "conversation");
				clearLoop(ctx);
				if (!ctx.isIdle()) ctx.abort();
				ctx.ui.notify(`Cleared opsx-loop: ${c}`, "info");
				return;
			}

			if (parsed.mode === "models") {
				// Thin wrapper over the `opsx models` CLI (owner of the write); bare → list.
				// Use the session cwd so `--layer project` targets the ACTIVE repo.
				const margs = parsed.args.length > 0 ? parsed.args : ["list"];
				const { out } = runModels(margs, ctx.cwd);
				ctx.ui.notify(out || "(no output)", "info");
				return;
			}

			if (parsed.mode === "goal") {
				// Goal/conversation kickoff: no change name yet. Snapshot existing change
				// dirs, inject the distill directive, and detect the new change on agent_end.
				// Pre-change (distilling) budget: configurable via OPSX_DISTILL_MAX_TURNS
				// (positive integer). Unset = unbounded; the distill stall guard
				// (lastDirs, STALL_LIMIT) is the backstop either way.
				const distillRaw = process.env.OPSX_DISTILL_MAX_TURNS;
				const distillBudget =
					distillRaw && /^\d+$/.test(distillRaw) && Number.parseInt(distillRaw, 10) > 0
						? Number.parseInt(distillRaw, 10)
						: undefined;
				loop = {
					goal: parsed.goal,
					awaitingChange: true,
					preChangeDirs: listChangeDirs(ctx.cwd),
					turns: 0,
					maxTurns: distillBudget, // replaced by the change's own budget on adoption
					active: true,
					evaluating: false,
					stallCount: 0,
				};
				renderStatus(ctx);
				pi.sendUserMessage(distillDirective(parsed.goal), { deliverAs: "followUp" });
				const src = parsed.goal ? `goal: "${parsed.goal}"` : "the current conversation";
				ctx.ui.notify(`⟳ opsx-loop started from ${src} — distilling intent → change (budget ${loop.maxTurns ?? "∞"}).`, "info");
				return;
			}

			// set — replaces any active loop, resolves worktree + budget, starts work.
			// Turn-0 short-circuit: if the change ALREADY passes opsx gate, do NOT arm or
			// inject a worker turn — re-kicking a finished (green) change would loop it
			// forever. Report it ready to archive instead.
			const wt0 = resolveWorktree(parsed.change, ctx.cwd);
			const pre = await runGate(parsed.change, wt0, ctx.signal, ctx.cwd);
			if (pre.met) {
				clearLoop(ctx);
				ctx.ui.notify(`⟳ opsx-loop: ${parsed.change} already passes opsx gate — ready to archive. Not starting a loop.`, "info");
				return;
			}
			const review = readReview(parsed.change, ctx.cwd);
			loop = {
				change: parsed.change,
				awaitingChange: false,
				worktree: wt0,
				turns: 0,
				maxTurns: parseLoopBudget(review),
				active: true,
				evaluating: false,
				stallCount: 0,
			};
			renderStatus(ctx);
			const exported = exportModelEnv(parsed.change, ctx.cwd);
			pi.sendUserMessage(workerDirective(parsed.change), { deliverAs: "followUp" });
			const modelNote = exported.length > 0 ? ` · models: ${exported.join(", ")}` : "";
			const ignoredNote = parsed.ignored ? ` (ignored extra input: "${parsed.ignored}")` : "";
			ctx.ui.notify(`⟳ opsx-loop started (budget ${loop.maxTurns ?? "∞"}) for ${parsed.change}${modelNote}${ignoredNote}`, "info");
			return;
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
			const c = loop.change ?? (loop.goal ? `goal "${loop.goal}"` : "conversation");
			clearLoop(ctx);
			ctx.ui.notify(`⟳ opsx-loop stopped (${stopReason}): ${c}`, "warning");
			return;
		}

		const session = loop;
		session.evaluating = true;
		try {
			session.turns += 1;

			// Goal/conversation mode: the agent is distilling intent into a NEW change.
			// Wait for its frozen intent.md, then adopt that change and arm the gate loop.
			// Until then, keep nudging with the distill directive (bounded by the budget).
			// (opsx-loop-kickoff.goal-and-conversation-kickoff)
			if (session.awaitingChange) {
				const detected = detectNewChange(session.preChangeDirs ?? [], ctx.cwd);
				if (!detected) {
					const src = session.goal ? `goal "${session.goal}"` : "the conversation";
					if (session.maxTurns !== undefined && session.turns >= session.maxTurns) {
						clearLoop(ctx);
						ctx.ui.notify(`⟳ opsx-loop: budget ${session.maxTurns} exhausted before a change was created from ${src}.`, "warning");
						return;
					}
					// Distill stall guard: under an unbounded budget, a kickoff that never
					// yields a new change with a frozen intent.md would re-inject the distill
					// directive forever (e.g. when an existing change already captures the
					// intent). Stop after STALL_LIMIT consecutive turns with NO change-dir
					// progress (no new dir appeared since the prior turn).
					const curDirs = listChangeDirs(ctx.cwd);
					const prevDirs = session.lastDirs;
					const dirsChanged =
						prevDirs === undefined ||
						curDirs.length !== prevDirs.length ||
						curDirs.some((n) => !prevDirs.includes(n));
					session.lastDirs = curDirs;
					if (dirsChanged) {
						session.stallCount = 0;
					} else {
						session.stallCount += 1;
						if (session.stallCount >= STALL_LIMIT) {
							clearLoop(ctx);
							ctx.ui.notify(`⟳ opsx-loop: no new change with a frozen intent.md appeared after ${STALL_LIMIT} turns distilling ${src}; stopping. If an existing change already captures this, drive it with /opsx-loop <change> or archive it.`, "warning");
							return;
						}
					}
					renderStatus(ctx);
					pi.sendUserMessage(distillDirective(session.goal), { deliverAs: "followUp" });
					return;
				}
				session.change = detected;
				session.awaitingChange = false;
				session.stallCount = 0; // reset counter on change adoption
				session.maxTurns = parseLoopBudget(readReview(detected, ctx.cwd));
				const exported = exportModelEnv(detected, ctx.cwd);
				const modelNote = exported.length > 0 ? ` · models: ${exported.join(", ")}` : "";
				ctx.ui.notify(`⟳ opsx-loop: change "${detected}" created — gating it now.${modelNote}`, "info");
			}
			const change = session.change as string;

			// Re-resolve the worktree EACH turn: a from-scratch change may only gain a
			// Worktree Path mid-loop. (opsx-loop-kickoff.opsx-gate-is-the-deterministic-judge)
			const prevWorktree = session.worktree;
			session.worktree = resolveWorktree(change, ctx.cwd);
			renderStatus(ctx);

			const verdict = await runGate(change, session.worktree, ctx.signal, ctx.cwd);
			if (loop !== session || !session.active) return; // cleared during async gate run
			session.lastReason = verdict.reason;

			if (verdict.met) {
				const c = session.change;
				clearLoop(ctx);
				ctx.ui.notify(`⟳ opsx-loop: ${c} — gate green. Ready to archive.`, "info");
				return;
			}
			if (session.maxTurns !== undefined && session.turns >= session.maxTurns) {
				const c = session.change;
				clearLoop(ctx);
				ctx.ui.notify(`⟳ opsx-loop: budget ${session.maxTurns} exhausted for ${c}; worktree preserved.`, "warning");
				return;
			}

			// Stall detection: same normalized failed-check set + no observable progress
			// + same worktree, for STALL_LIMIT turns running. WHILE the sole failing check
			// is `doneness` with a not/absent/unparseable verdict, "progress" is the judge's
			// gap set strictly shrinking against a running minimum (NOT change-dir content),
			// so file churn that closes no judged gap trips the stall under an unbounded budget.
			const key = gateFailKey(verdict.reason);
			const worktreeChanged = prevWorktree !== session.worktree;
			const sameFailure = !worktreeChanged && key !== "" && key === session.stallKey;
			const doneness = key === "doneness" ? readDoneness(change, session.worktree, ctx.cwd) : undefined;
			let noProgress: boolean;
			if (doneness && doneness.state === "gap") {
				// Bounded gap-set ratchet signal.
				if (!sameFailure) {
					session.minGaps = doneness.gaps.length > 0 ? doneness.gaps.slice() : undefined;
					noProgress = false; // streak (re)started this turn
				} else {
					const r = donenessRatchet(session.minGaps, doneness.gaps);
					session.minGaps = r.min;
					noProgress = !r.progress;
				}
				// content/HEAD lastProgress intentionally NOT consulted in gap mode
			} else {
				// Ordinary content/HEAD signal (also for a `satisfied` verdict failing on
				// freshness/provenance, which is re-judged next turn).
				const progress = progressToken(change, session.worktree, ctx.cwd);
				noProgress = sameFailure && progress === session.lastProgress;
				session.lastProgress = progress;
				session.minGaps = undefined; // reset the ratchet outside the gap-blocked state
			}
			if (sameFailure && noProgress) {
				session.stallCount += 1;
			} else {
				session.stallCount = 1;
			}
			session.stallKey = key;
			if (session.stallCount >= STALL_LIMIT) {
				const c = session.change;
				clearLoop(ctx);
				ctx.ui.notify(`⟳ opsx-loop: ${c} stalled on a repeating failure (${STALL_LIMIT}× no progress); worktree preserved. Intervene manually.`, "warning");
				return;
			}
			pi.sendUserMessage(workerDirective(change, verdict.reason), { deliverAs: "followUp" });
		} finally {
			session.evaluating = false;
		}
	});
}
