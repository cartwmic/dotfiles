/**
 * Library spawn adapter: opsx-loop → pi-subagents runSync (one-way; OPSX-blind).
 * Forwards onUpdate, provisions session/artifacts dirs, returns full SingleResult
 * metadata for Details. Strips agent.fallbackModels so role modelOverride is sole
 * candidate. Renderers: thin-wrap (import of render.ts fails outside pi's jiti
 * virtual-module aliases — intent allows "import or thin wrap").
 * (opsx-loop.dispatch-spawns-via-subagent-library,
 *  opsx-loop.opsx-dispatch-transparent-progress-and-details)
 */
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { homedir, tmpdir } from "node:os";
import { pathToFileURL } from "node:url";
import type {
	OpsxDispatchOnUpdate,
	OpsxDispatchSingleResult,
	OpsxDispatchSpawnResult,
	OpsxDispatchSpawnSpec,
} from "./helpers.ts";

const SUBAGENTS_DIR = join(homedir(), ".pi", "agent", "git", "github.com", "cartwmic", "pi-subagents");

type AgentToolResult = {
	content: Array<{ type: string; text?: string }>;
	details?: {
		mode?: string;
		results?: OpsxDispatchSingleResult[];
		progress?: OpsxDispatchSingleResult["progress"][];
	};
};

type AgentLike = { name: string; fallbackModels?: string[]; [k: string]: unknown };

type RunSyncFn = (
	runtimeCwd: string,
	agents: AgentLike[],
	agentName: string,
	task: string,
	options: {
		runId: string;
		modelOverride?: string;
		cwd?: string;
		signal?: AbortSignal;
		index?: number;
		sessionDir?: string;
		sessionFile?: string;
		artifactsDir?: string;
		onUpdate?: (r: AgentToolResult) => void;
	},
) => Promise<OpsxDispatchSingleResult & { exitCode: number; error?: string; finalOutput?: string }>;

type DiscoverFn = (cwd: string, scope: "user" | "project" | "both") => { agents: AgentLike[] };
type GetArtifactsDirFn = (parentSessionFile: string | null) => string;

type SubagentsApi = {
	runSync: RunSyncFn;
	discoverAgents: DiscoverFn;
	getArtifactsDir: GetArtifactsDirFn;
};

/** Process-singleton: parallel fan-out must share one dynamic import (avoids jiti race). */
let apiPromise: Promise<SubagentsApi> | undefined;

async function loadSubagentsApi(): Promise<SubagentsApi> {
	if (!apiPromise) {
		apiPromise = (async (): Promise<SubagentsApi> => {
			const executionUrl = pathToFileURL(join(SUBAGENTS_DIR, "execution.ts")).href;
			const agentsUrl = pathToFileURL(join(SUBAGENTS_DIR, "agents.ts")).href;
			const artifactsUrl = pathToFileURL(join(SUBAGENTS_DIR, "artifacts.ts")).href;
			const [execution, agents, artifacts] = await Promise.all([
				import(executionUrl),
				import(agentsUrl),
				import(artifactsUrl),
			]);
			return {
				runSync: execution.runSync as RunSyncFn,
				discoverAgents: agents.discoverAgents as DiscoverFn,
				getArtifactsDir: artifacts.getArtifactsDir as GetArtifactsDirFn,
			};
		})();
		// Failed load must not poison later spawns — allow retry.
		apiPromise.catch(() => {
			apiPromise = undefined;
		});
	}
	return apiPromise;
}

/** Role sole-source: clear fallbackModels so runSync cannot retry off-role models. */
export function agentsWithoutFallbacks(agents: AgentLike[], agentName: string): AgentLike[] {
	return agents.map((a) => {
		if (a.name !== agentName) return a;
		const { fallbackModels: _drop, ...rest } = a;
		return { ...rest, name: a.name };
	});
}

/** Pass through runSync SingleResult; ensure index + forced model on progress. */
export function toSingleResult(
	spec: OpsxDispatchSpawnSpec,
	result: OpsxDispatchSingleResult & { exitCode: number; error?: string; finalOutput?: string },
	index: number,
): OpsxDispatchSingleResult {
	const progress = result.progress
		? { ...result.progress, index, model: result.progress.model ?? spec.model }
		: {
				index,
				agent: spec.agent,
				status: (result.exitCode === 0 && !result.error ? "completed" : "failed") as
					| "completed"
					| "failed",
				task: spec.task,
				recentTools: [],
				recentOutput: [] as string[],
				toolCount: 0,
				tokens: 0,
				durationMs: 0,
				model: spec.model,
				error: result.error,
			};
	return {
		...result,
		agent: result.agent ?? spec.agent,
		task: result.task ?? spec.task,
		exitCode: result.exitCode,
		model: result.model ?? spec.model,
		progress,
	};
}

/** Default production spawn: pi-subagents runSync with forced modelOverride + onUpdate. */
export async function spawnViaRunSync(
	spec: OpsxDispatchSpawnSpec,
	opts: {
		cwd: string;
		signal?: AbortSignal;
		runId?: string;
		index?: number;
		onUpdate?: OpsxDispatchOnUpdate;
		/** Parent session file for artifact dir scoping (optional). */
		parentSessionFile?: string | null;
	},
): Promise<OpsxDispatchSpawnResult> {
	const index = opts.index ?? 0;
	try {
		const { runSync, discoverAgents, getArtifactsDir } = await loadSubagentsApi();
		const { agents: discovered } = discoverAgents(opts.cwd, "both");
		const agents = agentsWithoutFallbacks(discovered, spec.agent);
		const runId =
			opts.runId ?? `opsx-dispatch-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
		const sessionDir = join(tmpdir(), `opsx-dispatch-${runId}`);
		mkdirSync(sessionDir, { recursive: true });
		const sessionFile = join(sessionDir, "session.jsonl");
		const artifactsDir = getArtifactsDir(opts.parentSessionFile ?? null);
		mkdirSync(artifactsDir, { recursive: true });

		const result = await runSync(opts.cwd, agents, spec.agent, spec.task, {
			runId,
			modelOverride: spec.model,
			cwd: opts.cwd,
			signal: opts.signal,
			index,
			sessionDir,
			sessionFile,
			artifactsDir,
			onUpdate: opts.onUpdate
				? (u) => {
						const r0 = u.details?.results?.[0];
						const single = r0
							? toSingleResult(spec, { ...r0, exitCode: r0.exitCode ?? -1 }, index)
							: toSingleResult(
									spec,
									{
										agent: spec.agent,
										task: spec.task,
										exitCode: -1,
										finalOutput: "",
									},
									index,
								);
						opts.onUpdate!({
							content: u.content
								.filter(
									(c): c is { type: "text"; text: string } =>
										c.type === "text" && typeof c.text === "string",
								)
								.map((c) => ({ type: "text" as const, text: c.text! })),
							details: {
								mode: "single",
								results: [single],
								progress: single.progress ? [single.progress] : undefined,
								...(single.artifactPaths
									? {
											artifacts: {
												dir:
													(single.artifactPaths as { dir?: string }).dir ??
													artifactsDir,
											},
										}
									: { artifacts: { dir: artifactsDir } }),
							},
						});
					}
				: undefined,
		});
		const ok = result.exitCode === 0 && !result.error;
		const singleResult: OpsxDispatchSingleResult = {
			...toSingleResult(spec, result, index),
			// Surface the provisioned artifacts root for Details.artifacts aggregation
			// (ArtifactPaths itself has input/output/jsonl/metadata paths, not dir).
			artifactPaths: {
				...(result.artifactPaths ?? {}),
				dir: artifactsDir,
			} as OpsxDispatchSingleResult["artifactPaths"] & { dir: string },
		};
		// Prefer child finalOutput; never collapse to the old one-liner when output exists.
		const text =
			result.finalOutput?.trim() ||
			(result.error
				? `spawn error (${spec.model}): ${result.error}`
				: [
						`opsx_dispatch ${spec.agent} model=${spec.model} exit=${result.exitCode}`,
						singleResult.sessionFile ? `session=${singleResult.sessionFile}` : null,
						singleResult.artifactPaths
							? `artifacts=${JSON.stringify(singleResult.artifactPaths)}`
							: `artifactsDir=${artifactsDir}`,
					]
						.filter(Boolean)
						.join(" "));
		return { model: spec.model, agent: spec.agent, ok, text, singleResult };
	} catch (e: unknown) {
		const msg = e instanceof Error ? e.message : String(e);
		const text = `opsx_dispatch spawn failed to load pi-subagents runSync: ${msg}`;
		return {
			model: spec.model,
			agent: spec.agent,
			ok: false,
			text,
			singleResult: {
				agent: spec.agent,
				task: spec.task,
				exitCode: 1,
				error: text,
				finalOutput: "",
				model: spec.model,
				progress: {
					index,
					agent: spec.agent,
					status: "failed",
					task: spec.task,
					recentTools: [],
					recentOutput: [],
					toolCount: 0,
					tokens: 0,
					durationMs: 0,
					model: spec.model,
					error: text,
				},
			},
		};
	}
}



type Theme = {
	fg: (name: string, text: string) => string;
	bold: (text: string) => string;
};

/**
 * Thin-wrap renderCall text — mirrors pi-subagents themed call line.
 * index.ts wraps in pi-tui Text (keeps spawn.ts hermetic for bun tests).
 */
export function formatOpsxDispatchCall(
	args: { role?: string; tasks?: unknown[]; task?: string },
	theme: Theme,
): string {
	const role = typeof args.role === "string" ? args.role : "?";
	const isParallel = Array.isArray(args.tasks) && args.tasks.length > 0;
	const parallelCount = isParallel ? args.tasks!.length : 0;
	const title = theme.fg("toolTitle", theme.bold("opsx_dispatch "));
	if (isParallel) {
		return `${title}${theme.fg("accent", role)} parallel (${parallelCount})`;
	}
	return `${title}${theme.fg("accent", role)}`;
}

/**
 * Thin-wrap renderResult text — shows subagent-shaped Details (mode / progress /
 * tokens / tools / session / artifacts), not a one-liner.
 */
export function formatOpsxDispatchResult(
	result: {
		content?: Array<{ type?: string; text?: string }>;
		details?: {
			mode?: string;
			results?: OpsxDispatchSingleResult[];
			progress?: OpsxDispatchSingleResult["progress"][];
			artifacts?: { dir?: string };
			refused?: boolean;
			reason?: string;
		};
	},
	_options: { expanded?: boolean },
	theme: Theme,
): string {
	const d = result.details;
	if (d?.refused) {
		const t = result.content?.[0]?.text ?? `refused: ${d.reason ?? "?"}`;
		return theme.fg("error", String(t).slice(0, 400));
	}
	const results = d?.results ?? [];
	const mode = d?.mode ?? (results.length > 1 ? "parallel" : "single");
	const lines: string[] = [];
	lines.push(
		`${theme.fg("toolTitle", theme.bold("opsx_dispatch "))}[${mode}] ${results.length} result(s)`,
	);
	for (const r of results.slice(0, 8)) {
		const prog = r.progress;
		const status = prog?.status ?? (r.exitCode === 0 ? "completed" : "failed");
		const glyph =
			status === "running"
				? "…"
				: status === "pending"
					? "·"
					: r.exitCode === 0 && !r.error
						? "✓"
						: "✗";
		const stats = [
			prog?.model ?? r.model,
			prog ? `${prog.toolCount} tools` : null,
			prog ? `${prog.tokens} tok` : null,
			prog ? `${Math.round(prog.durationMs)}ms` : null,
			r.sessionFile ? `session=${r.sessionFile}` : null,
		]
			.filter(Boolean)
			.join(" · ");
		lines.push(`  ${glyph} ${r.agent}: ${status}${stats ? ` (${stats})` : ""}`);
		const out = (r.finalOutput ?? "").trim();
		if (out) {
			const preview = out.split("\n")[0]!.slice(0, 120);
			lines.push(`      ${preview}${out.length > 120 ? "…" : ""}`);
		}
	}
	if (d?.artifacts?.dir) {
		lines.push(`  artifacts: ${d.artifacts.dir}`);
	}
	if (results.length === 0) {
		const t = result.content?.[0]?.text ?? "(no output)";
		lines.push(`  ${String(t).slice(0, 200)}`);
	}
	return lines.join("\n");
}
