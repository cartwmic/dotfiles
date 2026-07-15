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
import { existsSync, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";
import {
	buildModelEnv,
	classifyDoneness,
	donenessRatchet,
	formatInventory,
	gateFailKey,
	hashDir,
	listIntentChanges,
	LOOP_SUBCOMMANDS,
	OPSX_MODEL_ENV_KEYS,
	OPSX_DISPATCH_TOOL_NAME,
	applyArmedToolSet,
	restoreToolSetAfterClear,
	planOpsxDispatch,
	runOpsxDispatchSpawns,
	type OpsxDispatchRole,
	resolveCompactThresholdTokens,
	resolveElideMaxKeepTokens,
	resolveElideBandTokens,
	elideToolResultBodies,
	describeCompactPolicy,
	isContextOverflowError,
	parseDonenessGaps,
	parseLoopArg,
	clearHoldText,
	parseLoopBudget,
	parseLoopHold,
	parseModelsJson,
	verdictFromExit,
	type LoopVerdict,
	type ResolvedModel,
} from "./helpers.ts";
import { Type } from "typebox";
<<<<<<< HEAD
import {
	classifyModelsCommand,
	shouldRunInteractiveModelsSet,
} from "./model-config.ts";
import { runInteractiveModelsSet } from "./model-config-ui.ts";
=======
>>>>>>> f1ddd2d (fix: honor concurrency, presence XOR, sole-model, renderer preload)
import { spawnViaRunSync, loadSubagentRenderers, type SubagentRenderers } from "./spawn.ts";
import { Text } from "@mariozechner/pi-tui";

const STALL_LIMIT = 3; // consecutive identical no-progress gate failures → stop

// Custom compaction instructions for the proactive between-turns pass (Lever A).
// The opsx-loop is fully resumable from disk: every turn re-derives its state from
// `opsx gate <change> --worktree <path>` and openspec/changes/<change>/, and the
// writeback discipline commits all verdicts/ledger/holds BEFORE a turn ends. So the
// summary need only preserve the pointers to that on-disk state; the reasoning and
// tool-output bodies are re-derivable and safe to drop. Keeping this tight is the
// whole point on small context windows.
const OPSX_COMPACT_INSTRUCTIONS =
	"This is an autonomous opsx-loop drive-to-green run. ALL loop state is recoverable " +
	"from `opsx gate <change> --worktree <path>` and the openspec/changes/<change>/ files " +
	"(intent.md, proposal, specs, tasks.md, review.md, code-review.md, doneness.md). " +
	"Preserve ONLY: the change name, the worktree path, the resolved role models, the last " +
	"gate verdict and its earliest failing check, and any decision made this turn that is " +
	"NOT yet written to disk. DROP tool-output bodies, file contents, and prior reasoning " +
	"— the next turn re-reads them from the gate and the change directory.";

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
	// True while a proactive between-turns compaction (Lever A) is in flight: the
	// worker directive is injected in the compaction callback, so a stray agent_end
	// in that window must NOT re-run the gate or double-inject.
	compacting?: boolean;
	// Set by the mid-run `context`-event elision transform (Lever L3) when it elides
	// at least one stale tool-result body during THIS run. Read once at agent_end to
	// couple elision → between-turns compaction (force the L1 compact path so the
	// ephemeral trim is durably consolidated), then reset. Self-rate-limited: a
	// compacted run starts slim, so elision does not re-fire until history regrows.
	elided?: boolean;
	// Bounded latch for overflow-only recovery: set when a worker turn ends with a
	// context-overflow error and we compact-and-retry once; reset on the next clean
	// turn. A second consecutive overflow (recovery already attempted) stops the loop.
	overflowRecoveryAttempted?: boolean;
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
 * (opsx-loop.goal-and-conversation-kickoff)
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
 * (opsx-loop.loop-exports-resolved-role-models)
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

/**
 * Convention-path fallback: the canonical path from the single-source read-only
 * `opsx worktree path` emit, used iff it is a valid git worktree on branch
 * opsx/<change>. Never re-derives the path locally.
 * (opsx-loop.worktree-resolution-convention-fallback)
 */
/** True iff `p` is a git worktree checked out on branch opsx/<change>. */
function isChangeWorktree(p: string, change: string): boolean {
	try {
		const b = spawnSync("git", ["-C", p, "rev-parse", "--abbrev-ref", "HEAD"], { encoding: "utf-8", timeout: 5000 });
		return b.status === 0 && (b.stdout ?? "").trim() === `opsx/${change}`;
	} catch {
		return false;
	}
}

function conventionWorktree(change: string, cwd: string): string | undefined {
	try {
		const r = spawnSync("opsx", ["worktree", "path", change], { encoding: "utf-8", cwd, timeout: 5000 });
		const p = r.status === 0 ? (r.stdout ?? "").trim() : "";
		if (!p) return undefined;
		return isChangeWorktree(p, change) ? p : undefined;
	} catch {
		return undefined;
	}
}

/**
 * Re-resolve a usable worktree path: the review.md locator first — validated as
 * a git worktree ON BRANCH opsx/<change>, so a stale locator pointing at some
 * other tree cannot suppress the fallback — then the convention fallback; else
 * undefined (no --worktree, unchanged degraded behavior).
 */
function resolveWorktree(change: string, cwd: string): string | undefined {
	const wt = bodyField(readReview(change, cwd), "Worktree Path");
	if (wt && isChangeWorktree(wt, change)) return wt;
	return conventionWorktree(change, cwd);
}

/**
 * Change names whose intent.md is COMMITTED at HEAD — `git ls-tree HEAD`, not
 * `ls-files`: a merely STAGED draft is not a committed/frozen baseline and must
 * not be inventoried as resumable.
 */
function committedIntentNames(cwd: string): Set<string> {
	try {
		const r = spawnSync("git", ["-C", cwd, "ls-tree", "-r", "--name-only", "HEAD", "--", "openspec/changes"], {
			encoding: "utf-8",
			timeout: 5000,
		});
		if (r.status !== 0) return new Set();
		const names = new Set<string>();
		for (const line of (r.stdout ?? "").split("\n")) {
			const m = line.trim().match(/^openspec\/changes\/([^/]+)\/intent\.md$/);
			if (m && m[1] !== "archive") names.add(m[1]);
		}
		return names;
	} catch {
		return new Set();
	}
}

/**
 * A token capturing observable progress: worktree HEAD + dirty status of the
 * change dir. A change in either between evaluations resets the stall counter
 * (committed OR uncommitted in-place authoring counts as progress).
 * (opsx-loop.stall-detection-stops-the-loop)
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
 * the gate's free-text message). (opsx-loop.stall-detection-stops-the-loop)
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
	/** Pre-arm active tool snapshot; restored on clear/stop. */
	let toolsBeforeArm: string[] | undefined;
	let opsxDispatchRegistered = false;

	function ensureOpsxDispatchTool(): void {
		if (opsxDispatchRegistered) return;
		opsxDispatchRegistered = true;
		let cachedRenderers: SubagentRenderers | null | undefined;
		const renderersPromise = loadSubagentRenderers().then((r) => {
			cachedRenderers = r;
			return r;
		});
		// Warm immediately so first renderResult rarely hits fallback.
		void renderersPromise;
		pi.registerTool({
			name: OPSX_DISPATCH_TOOL_NAME,
			label: "opsx_dispatch",
			description:
				"Armed-loop-only: dispatch role-bound subagent work (review/impl/author) with the resolved opsx role model forced. Accepts `task` or parallel `tasks[]`. Review multi-list + single task expands to native parallel. Refuses when no loop is armed or the role is unset.",
			parameters: Type.Object({
				role: Type.Union([Type.Literal("review"), Type.Literal("impl"), Type.Literal("author")], {
					description: "opsx role whose configured model is forced for the spawn",
				}),
				task: Type.Optional(Type.String({ description: "Single task prompt (mutually exclusive with tasks)" })),
				tasks: Type.Optional(
					Type.Array(
						Type.Object({
							task: Type.String(),
							agent: Type.Optional(Type.String()),
							model: Type.Optional(
								Type.String({ description: "Ignored — role is sole model source" }),
							),
						}),
						{ description: "PARALLEL tasks (mutually exclusive with task)" },
					),
				),
				agent: Type.Optional(Type.String({ description: "Optional default subagent agent name" })),
				concurrency: Type.Optional(
					Type.Number({ description: "Max concurrent parallel spawns (default 4; mirrors pi-subagents)" }),
				),
				model: Type.Optional(
					Type.String({
						description: "Ignored when role is configured — role is sole model source",
					}),
				),
			}),
			async execute(_toolCallId, params, signal, onUpdate, ctx) {
				const role = params.role as OpsxDispatchRole;
				const authorInSession = resolveModel("author-in-session", loop?.change ?? "", ctx.cwd);
				const ais =
					authorInSession && typeof authorInSession.value === "boolean"
						? authorInSession.value
						: true;
				const resolved = loop?.change
					? resolveModel(role === "author" ? "author" : role, loop.change, ctx.cwd)
					: null;
				const plan = planOpsxDispatch({
					armed: Boolean(loop?.active && loop.change && !loop.awaitingChange),
					role,
					task: params.task,
					tasks: params.tasks,
					taskProvided: Object.prototype.hasOwnProperty.call(params, "task"),
					tasksProvided: Object.prototype.hasOwnProperty.call(params, "tasks"),
					agent: params.agent,
					concurrency: params.concurrency,
					callerModel: params.model,
					resolved,
					authorInSession: ais,
				});
				if (!plan.ok) {
					return {
						content: [{ type: "text", text: plan.message }],
						details: { refused: true, reason: plan.reason, mode: "management", results: [] },
					};
				}
				const { results, details, text } = await runOpsxDispatchSpawns(
					plan,
					(spec, meta) =>
						spawnViaRunSync(spec, {
							cwd: ctx.cwd,
							signal,
							index: meta.index,
							onUpdate: meta.onUpdate,
						}),
					{
						onUpdate: onUpdate
							? (u) => {
									onUpdate({
										content: u.content,
										details: u.details,
									});
								}
							: undefined,
					},
				);
				const allOk = results.every((r) => r.ok);
				return {
					content: [{ type: "text", text }],
					details: {
						...details,
						refused: false,
						models: results.map((r) => r.model),
						ok: allOk,
						count: results.length,
					},
				};
			},
			// Mirror pi-subagents renderCall structure (not exported from the package).
			renderCall(args, theme) {
				const role = typeof args.role === "string" ? args.role : "?";
				const isParallel = Array.isArray(args.tasks) && args.tasks.length > 0;
				const parallelCount = isParallel ? args.tasks.length : 0;
				const title = theme.fg("toolTitle", theme.bold("opsx_dispatch "));
				if (isParallel) {
					return new Text(
						`${title}${theme.fg("accent", role)} parallel (${parallelCount})`,
						0,
						0,
					);
				}
				return new Text(`${title}${theme.fg("accent", role)}`, 0, 0);
			},
			renderResult(result, options, theme, context) {
				if (cachedRenderers === undefined) {
<<<<<<< HEAD
=======
					// Still warming — invalidate when ready so TUI re-renders with real renderer.
>>>>>>> f1ddd2d (fix: honor concurrency, presence XOR, sole-model, renderer preload)
					void renderersPromise.then(() => {
						try {
							context?.invalidate?.();
						} catch {
							/* ignore */
						}
					});
				}
				if (cachedRenderers) {
					try {
						cachedRenderers.syncResultAnimation(result as never, context as never);
						return cachedRenderers.renderSubagentResult(result as never, options, theme) as never;
					} catch {
						/* fall through */
					}
				}
				const t = result.content?.[0];
				const text =
					t && typeof t === "object" && "text" in t
						? String((t as { text: string }).text)
						: "(no output)";
				return new Text(text.slice(0, 200), 0, 0);
			},
		});
	}

	function armRoleDispatchTools(): void {
		ensureOpsxDispatchTool();
		if (toolsBeforeArm === undefined) {
			toolsBeforeArm = pi.getActiveTools();
		}
		pi.setActiveTools(applyArmedToolSet(toolsBeforeArm));
	}

	function restoreRoleDispatchTools(): void {
		const next = restoreToolSetAfterClear(toolsBeforeArm, pi.getActiveTools());
		pi.setActiveTools(next);
		toolsBeforeArm = undefined;
	}

	function renderStatus(ctx: ExtensionContext): void {
		const label = loop?.change ?? (loop?.goal ? "(distilling goal)" : "(distilling)");
		const suffix = loop?.compacting ? " · compacting" : "";
		ctx.ui.setStatus(
			"opsx-loop",
			loop?.active ? `⟳ opsx-loop ${label} · ${loop.turns}/${loop.maxTurns ?? "∞"}${suffix}` : undefined,
		);
	}

	function clearLoop(ctx: ExtensionContext): void {
		if (toolsBeforeArm !== undefined || pi.getActiveTools().includes(OPSX_DISPATCH_TOOL_NAME)) {
			try {
				restoreRoleDispatchTools();
			} catch {
				/* best-effort restore; never block clear */
			}
		}
		loop = undefined;
		renderStatus(ctx);
	}

	// Inject the next worker continuation turn, optionally preceded by a proactive
	// context compaction (Lever A). DEFAULT-ON: when current context usage is at/above
	// the percent-only threshold (OPSX_COMPACT_AT_PERCENT, default 50% of the window),
	// compact FIRST and inject in the
	// completion callback so the next turn starts on a compacted context; otherwise
	// inject directly (current behavior). Degrades safely: if the running pi lacks
	// getContextUsage/compact, or usage is unknown (null right after a compaction),
	// we inject directly.
	// Inject an arbitrary continuation `directive`, optionally preceded by a proactive
	// compaction. Shared by the worker path (workerDirective) and the goal/conversation
	// distill path (distillContinuation) so the elision→compaction coupling and the L1
	// threshold decision are honored UNIFORMLY at every run boundary. Consumes the
	// per-run `elided` latch exactly once here.
	function injectWithOptionalCompact(
		session: LoopState,
		ctx: ExtensionContext,
		directive: string,
	): void {
		const inject = () => {
			// Guard: the loop may have been cleared/replaced during compaction.
			if (loop === session && session.active) {
				pi.sendUserMessage(directive, { deliverAs: "followUp" });
			}
		};

		const canMeasure = typeof ctx.getContextUsage === "function";
		const canCompact = typeof ctx.compact === "function";
		// Elision → compaction coupling (L3): if the mid-run elision transform fired
		// this run, force the L1 compact path so the ephemeral trim is durably
		// consolidated. Consume the flag here at the run boundary; the next run starts
		// slim and re-evaluates. Threshold measurement is still preferred for the
		// notify wording, but a forced compaction does not require a measurable usage.
		const forceCompact = session.elided === true;
		session.elided = false;
		if (!canCompact) {
			inject();
			return;
		}

		const usage = canMeasure ? ctx.getContextUsage() : undefined;
		const tokens = usage?.tokens;
		const window = usage?.contextWindow;
		let overThreshold = false;
		if (tokens != null && window != null) {
			const threshold = resolveCompactThresholdTokens(
				window,
				process.env.OPSX_COMPACT_AT_PERCENT,
			);
			overThreshold = threshold !== undefined && tokens >= threshold;
		}
		// Neither the L1 threshold nor an eliding run asks for a compaction (or usage is
		// unmeasurable and elision did not fire): inject directly and let the next turn
		// re-evaluate.
		if (!forceCompact && !overThreshold) {
			inject();
			return;
		}

		// Compact, then inject in the callback. `compacting` gates a stray agent_end out
		// of the compaction window; both callbacks clear it and inject so a compaction
		// error never drops the turn.
		session.compacting = true;
		renderStatus(ctx);
		const notifyMsg =
			overThreshold && tokens != null && window != null
				? `⟳ opsx-loop: context ${tokens.toLocaleString("en-US")}/${window.toLocaleString("en-US")} tokens ≥ threshold — compacting before next turn.`
				: `⟳ opsx-loop: mid-run elision fired — compacting before next turn to consolidate durably.`;
		ctx.ui.notify(notifyMsg, "info");
		const done = () => {
			session.compacting = false;
			renderStatus(ctx);
			inject();
		};
		try {
			ctx.compact({
				customInstructions: OPSX_COMPACT_INSTRUCTIONS,
				onComplete: done,
				onError: done,
			});
		} catch {
			// Synchronous throw (e.g. compaction already running): fail safe to a
			// direct inject so the loop never stalls.
			done();
		}
	}

	// Worker continuation: build the worker directive and inject it through the shared
	// compaction-aware path.
	function continueWorker(
		session: LoopState,
		ctx: ExtensionContext,
		change: string,
		reason: string,
	): void {
		injectWithOptionalCompact(session, ctx, workerDirective(change, reason));
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
	// Distill phase ONLY drafts the intent baseline; it does NOT proceed to
	// implementation. The extension pauses at intent detection for a one-shot
	// human confirmation (ADR-0014): the frozen intent.md is the immutable
	// baseline every blind reviewer and the doneness judge scores against, so
	// the loop being scored must not silently author-and-adopt it.
	// Distill-scoped autonomy (opsx-loop.goal-and-conversation-kickoff):
	// the drive-to-green AUTONOMY blurb must NEVER ride the distill directive —
	// "keep going, the gate is the arbiter" contradicts the directive's own STOP
	// and invites implementing during distill.
	const DISTILL_AUTONOMY =
		`\n\nDraft the intent AUTONOMOUSLY: do not ask the user questions while drafting — make ` +
		`the most reasonable decision from the goal/conversation and record assumptions in the ` +
		`draft. Do NOT implement anything, do NOT create worktrees or author further artifacts, ` +
		`and STOP after the announcement: the loop pauses for human intent confirmation.`;

	const distillDirective = (goal: string | undefined, cwd: string) => {
		const committed = committedIntentNames(cwd);
		const inventory = formatInventory(listIntentChanges(cwd, (n) => committed.has(n)));
		return (
			`Distill an OpenSpec change with a frozen intent baseline (draft only — do NOT start implementing).\n\n` +
			`Active changes with a committed intent.md (deterministic inventory):\n${inventory}\n\n` +
			`- If one of these already captures this work, do NOT create a new change: announce which ` +
			`one, advise the user to arm it with /opsx-loop <name>, and stop.\n` +
			(goal
				? `- Otherwise distill this goal into a new change: "${goal}".`
				: `- Otherwise distill our current conversation — the intent we have converged on — into a new change.`) +
			` Use openspec-explore / openspec-propose to create openspec/changes/<name>/ with intent.md.\n` +
			`Announce the new change name as soon as its intent.md is written, then STOP: the loop ` +
			`pauses for the user to review and confirm the intent baseline before the autonomous ` +
			`drive-to-green phase is armed with /opsx-loop <name>.` +
			DISTILL_AUTONOMY
		);
	};

	// Terse distill CONTINUATION nudge — mirrors the worker kickoff-vs-continuation
	// split (load-bearing): the inventory and full setup prose ride the KICKOFF
	// directive only, never this nudge.
	const distillContinuation = (goal?: string) =>
		`[still distilling] No new change with a committed intent.md has appeared yet. Continue the ` +
		`SAME distill task from the kickoff instructions: ` +
		(goal
			? `draft the intent for goal "${goal}" into openspec/changes/<name>/intent.md and announce it`
			: `draft the intent distilled from this conversation into openspec/changes/<name>/intent.md and announce it`) +
		`, OR — if an active change from the kickoff inventory already covers it — announce that change ` +
		`and advise /opsx-loop <name>, then stop. Do NOT implement; STOP after announcing.`;

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
				// Thin wrapper over `opsx models` (CLI owns writes). Bare → list.
				// Bare/role-only `set` with UI runs in-TUI pickers then shells out to
				// `opsx models set …` — extension never writes YAML. (Path B)
				const route = classifyModelsCommand(parsed.args);
				if (
					shouldRunInteractiveModelsSet(route, Boolean(ctx.hasUI), typeof ctx.ui?.custom === "function")
				) {
					const plan = await runInteractiveModelsSet(
						ctx,
						route.kind === "interactive-set" ? route.role : undefined,
					);
					if (!plan.ok) {
						ctx.ui.notify(plan.error, "error");
						return;
					}
					const { code, out } = runModels(plan.cliArgs, ctx.cwd);
					ctx.ui.notify(out || "(no output)", code === 0 ? "info" : "error");
					return;
				}
				const margs = route.kind === "list" ? ["list"] : parsed.args;
				const { code, out } = runModels(margs, ctx.cwd);
				ctx.ui.notify(out || "(no output)", code === 0 ? "info" : "error");
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
				const preDirs = listChangeDirs(ctx.cwd);
				loop = {
					goal: parsed.goal,
					awaitingChange: true,
					preChangeDirs: preDirs,
					turns: 0,
					maxTurns: distillBudget, // replaced by the change's own budget on adoption
					active: true,
					evaluating: false,
					stallCount: 0,
					// Seed the stall baseline at arm time so the FIRST distilling turn
					// counts and STALL_LIMIT means exactly STALL_LIMIT turns (D7 — the
					// undefined-baseline turn previously made 3 cost 4).
					lastDirs: preDirs.slice(),
				};
				renderStatus(ctx);
				pi.sendUserMessage(distillDirective(parsed.goal, ctx.cwd), { deliverAs: "followUp" });
				const src = parsed.goal ? `goal: "${parsed.goal}"` : "the current conversation";
				ctx.ui.notify(`⟳ opsx-loop started from ${src} — distilling intent → change (budget ${loop.maxTurns ?? "∞"}).`, "info");
				return;
			}

			// set — replaces any active loop, resolves worktree + budget, starts work.
			// Named re-arm clears any landing hold BEFORE the turn-0 gate evaluation and
			// regardless of its outcome (a green short-circuit must not leave a stale
			// hold behind). This explicit human-only spelling is the SOLE clear path —
			// goal kickoff never touches holds, agents cannot invoke slash commands.
			// (opsx-loop.loop-hold-blocks-continuation)
			let holdNote = "";
			const reviewMd0 = readReview(parsed.change, ctx.cwd);
			const hold0 = parseLoopHold(reviewMd0);
			if (hold0.held) {
				const reviewPath = join(ctx.cwd, "openspec", "changes", parsed.change, "review.md");
				try {
					const cleared = clearHoldText(reviewMd0, parsed.change, new Date().toISOString().slice(0, 10));
					writeFileSync(reviewPath, cleared.next);
					holdNote = ` · hold was set: "${cleared.reason || "(no reason recorded)"}" — cleared by re-arm`;
				} catch (e: any) {
					ctx.ui.notify(`⟳ opsx-loop: failed to clear loop_hold in ${reviewPath}: ${e?.message ?? "unknown"}`, "error");
					return;
				}
			}
			// Turn-0 short-circuit: if the change ALREADY passes opsx gate, do NOT arm or
			// inject a worker turn — re-kicking a finished (green) change would loop it
			// forever. Report it ready to archive instead.
			const wt0 = resolveWorktree(parsed.change, ctx.cwd);
			const pre = await runGate(parsed.change, wt0, ctx.signal, ctx.cwd);
			if (pre.met) {
				clearLoop(ctx);
				ctx.ui.notify(`⟳ opsx-loop: ${parsed.change} already passes opsx gate — ready to archive. Not starting a loop.${holdNote}`, "info");
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
			armRoleDispatchTools();
			pi.sendUserMessage(workerDirective(parsed.change), { deliverAs: "followUp" });
			const modelNote = exported.length > 0 ? ` · models: ${exported.join(", ")}` : "";
			const ignoredNote = parsed.ignored ? ` (ignored extra input: "${parsed.ignored}")` : "";
			ctx.ui.notify(`⟳ opsx-loop started (budget ${loop.maxTurns ?? "∞"}) for ${parsed.change}${modelNote}${ignoredNote}${holdNote}`, "info");
			// Surface the compaction policy at arm: this loop is the operator's SOLE
			// compaction path (pi auto-compaction off), so make the guard visible —
			// including when it has been explicitly turned off.
			ctx.ui.notify(
				`⟳ ${describeCompactPolicy(process.env.OPSX_COMPACT_AT_PERCENT)}`,
				"info",
			);
			return;
		},
	});

	// Mid-run context elision (Lever L3). The pi `context` event fires before EVERY
	// provider request within a run; the handler returns a slimmer per-request VIEW
	// (stale tool-result bodies stubbed) WITHOUT mutating stored history and WITHOUT
	// aborting the turn. Strict no-op unless a loop is armed and total context usage
	// exceeds the token budget (maxKeep + band); degrades to pass-through when the host
	// lacks the usage API. Returning undefined leaves the messages unchanged.
	// (opsx-loop-context-elision.active-loop-scoped-elision, .token-budget-boundary,
	//  .token-band-hysteresis, .elision-suppressed-during-compaction,
	//  .stale-tool-result-body-elision, .safe-degradation, .no-history-mutation)
	pi.on("context", (event: any, ctx: ExtensionContext) => {
		const session = loop;
		if (!session?.active) return undefined; // active-loop-only scope
		// Never elide the compaction summarizer's OWN request: a between-turns compaction
		// issues provider requests that also fire this event, and slimming them would feed
		// the summarizer a stubbed view of the very history it is consolidating.
		if (session.compacting) return undefined;
		if (typeof ctx.getContextUsage !== "function") return undefined; // safe-degrade
		const messages = event?.messages;
		if (!Array.isArray(messages) || messages.length === 0) return undefined;
		// Only the WINDOW size is read from usage — the activation/boundary decision runs
		// on the deterministic per-turn ESTIMATE of the messages ABOUT TO BE SENT (the same
		// total tokenBudgetBoundary uses), so the gate and the boundary can never disagree:
		// elision fires IFF the estimate exceeds maxKeep + band, and when it fires the
		// progress guarantee sheds at least the oldest turn (no fire-but-noop). Reading real
		// usage.tokens for a separate gate would let the handler "fire" while the estimate
		// finds nothing to elide (benign, but a needless dual-total).
		const window = ctx.getContextUsage()?.contextWindow;
		if (window == null) return undefined; // unknown window → pass-through (safe-degrade)
		const maxKeep = resolveElideMaxKeepTokens(window, process.env.OPSX_ELIDE_KEEP_RECENT_PERCENT);
		const band = resolveElideBandTokens(window, process.env.OPSX_ELIDE_BAND_PERCENT);
		if (maxKeep === undefined || band === undefined) return undefined; // unknown window
		// elideToolResultBodies self-gates on the estimate (returns elided:false when total
		// ≤ maxKeep + band), so no separate real-tokens threshold is needed here.
		const { messages: view, elided } = elideToolResultBodies(messages, {
			maxKeepTokens: maxKeep,
			bandTokens: band,
		});
		if (!elided) return undefined;
		session.elided = true; // couple to between-turns compaction at the run boundary
		return { messages: view };
	});

	pi.on("agent_end", async (event: any, ctx: ExtensionContext) => {
		// inactive, re-entrant (clarify C1), or a between-turns compaction is in flight
		// (Lever A: the worker directive is injected in the compaction callback).
		if (!loop?.active || loop.evaluating || loop.compacting) return;

		// User interrupted / turn errored → stop instead of re-injecting.
		const last = (Array.isArray(event?.messages) ? event.messages : [])
			.slice()
			.reverse()
			.find((m: any) => m?.role === "assistant");
		const stopReason: string | undefined = typeof last?.stopReason === "string" ? last.stopReason : undefined;
		if (stopReason === "aborted" || stopReason === "error") {
			const session = loop;
			// Consume the elision latch at this run boundary too: the overflow-recovery
			// branch below compacts (consolidating any elided content) and the stop paths
			// end the loop, so a run's `elided` must never leak into a later retried run
			// (which could otherwise force an elision-driven compaction on a non-elided
			// run — the coupling is strictly per-run).
			session.elided = false;
			// Overflow-ONLY recovery (general auto-compaction stays off): a worker turn
			// that ends with a CONTEXT-OVERFLOW error gets ONE compact-and-retry instead
			// of stopping — mirroring pi's built-in recovery that the operator's
			// compaction.enabled=false disables. Bounded by overflowRecoveryAttempted;
			// a second consecutive overflow stops the loop.
			const window =
				(typeof ctx.getContextUsage === "function" ? ctx.getContextUsage()?.contextWindow : undefined) ??
				(ctx.model as any)?.contextWindow;
			const isOverflow =
				stopReason === "error" &&
				!session.awaitingChange &&
				!!session.change &&
				typeof ctx.compact === "function" &&
				isContextOverflowError(last, window);
			if (isOverflow && !session.overflowRecoveryAttempted) {
				session.overflowRecoveryAttempted = true;
				const change = session.change as string;
				// Continuation directive (kickoff form if no gate report yet); after
				// compaction the retried turn re-reads the gate and resumes — the loop is
				// resumable from disk, so re-running the same unit of work is safe.
				const directive = workerDirective(change, session.lastReason);
				ctx.ui.notify(
					`⟳ opsx-loop: ${change} — context overflow; compacting and retrying once (auto-compaction stays off).`,
					"warning",
				);
				session.compacting = true;
				renderStatus(ctx);
				const done = () => {
					session.compacting = false;
					renderStatus(ctx);
					if (loop === session && session.active) {
						pi.sendUserMessage(directive, { deliverAs: "followUp" });
					}
				};
				try {
					ctx.compact({ customInstructions: OPSX_COMPACT_INSTRUCTIONS, onComplete: done, onError: done });
				} catch {
					done();
				}
				return;
			}
			const c = session.change ?? (session.goal ? `goal "${session.goal}"` : "conversation");
			clearLoop(ctx);
			ctx.ui.notify(
				isOverflow
					? `⟳ opsx-loop stopped: ${c} — context overflow persisted after a compact-and-retry; worktree preserved. Reduce scope or use a larger-context model, then re-arm with /opsx-loop ${session.change ?? ""}.`
					: `⟳ opsx-loop stopped (${stopReason}): ${c}`,
				"warning",
			);
			return;
		}

		const session = loop;
		session.evaluating = true;
		try {
			// A clean (non-error) turn re-arms one future overflow recovery.
			session.overflowRecoveryAttempted = false;
			session.turns += 1;

			// Goal/conversation mode: the agent is distilling intent into a NEW change.
			// Wait for its frozen intent.md, then adopt that change and arm the gate loop.
			// Until then, keep nudging with the distill directive (bounded by the budget).
			// (opsx-loop.goal-and-conversation-kickoff)
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
					// Distill continuation rides the SAME compaction-aware inject as the worker
					// path so a distill run in which mid-run elision fired still consumes the
					// `elided` latch and compacts to consolidate durably (coupling honored on
					// every run boundary, not just the worker path).
					injectWithOptionalCompact(session, ctx, distillContinuation(session.goal));
					return;
				}
				// ONE-SHOT HUMAN CONFIRM (ADR-0014): do NOT silently adopt the
				// agent-authored intent as the frozen baseline. Stop here; the user
				// reviews intent.md and arms the gate loop explicitly.
				clearLoop(ctx);
				ctx.ui.notify(
					`⟳ opsx-loop: change "${detected}" distilled — PAUSED for intent confirmation. ` +
						`Review openspec/changes/${detected}/intent.md (edit it now if the baseline is wrong — ` +
						`it is frozen once the loop starts), then arm the loop with: /opsx-loop ${detected}`,
					"info",
				);
				return;
			}
			const change = session.change as string;

			// loop_hold landing channel: checked FIRST, before any gate run or
			// continuation injection. The hold lives in the INTEGRATION-checkout
			// review.md (the copy this host resolves) and is honored even with an
			// empty reason — a malformed landing must still land (fail-safe).
			// Only the human named re-arm clears it.
			// (opsx-loop.loop-hold-blocks-continuation)
			const hold = parseLoopHold(readReview(change, ctx.cwd));
			if (hold.held) {
				clearLoop(ctx);
				ctx.ui.notify(
					`⟳ opsx-loop: ${change} — loop landed (loop_hold${hold.reason ? `: ${hold.reason}` : " set without a reason"}). ` +
						`Worktree preserved. Re-arm with /opsx-loop ${change} to clear the hold and continue.`,
					"warning",
				);
				return;
			}

			// Re-resolve the worktree EACH turn: a from-scratch change may only gain a
			// Worktree Path mid-loop. (opsx-loop.opsx-gate-is-the-deterministic-judge)
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
			continueWorker(session, ctx, change, verdict.reason);
		} finally {
			session.evaluating = false;
		}
	});
}
