/**
 * Library spawn adapter: opsx-loop → pi-subagents runSync (one-way; OPSX-blind).
 * Forwards onUpdate and returns SingleResult-shaped payload for Details.
 * Strips agent.fallbackModels so role modelOverride is the sole candidate.
 * (opsx-loop.dispatch-spawns-via-subagent-library,
 *  opsx-loop.opsx-dispatch-transparent-progress-and-details)
 */
import { join } from "node:path";
import { homedir } from "node:os";
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
		onUpdate?: (r: AgentToolResult) => void;
	},
) => Promise<OpsxDispatchSingleResult & { exitCode: number; error?: string; finalOutput?: string }>;

type DiscoverFn = (cwd: string, scope: "user" | "project" | "both") => { agents: AgentLike[] };

async function loadSubagentsApi(): Promise<{ runSync: RunSyncFn; discoverAgents: DiscoverFn }> {
	const executionUrl = pathToFileURL(join(SUBAGENTS_DIR, "execution.ts")).href;
	const agentsUrl = pathToFileURL(join(SUBAGENTS_DIR, "agents.ts")).href;
	const [execution, agents] = await Promise.all([import(executionUrl), import(agentsUrl)]);
	return {
		runSync: execution.runSync as RunSyncFn,
		discoverAgents: agents.discoverAgents as DiscoverFn,
	};
}

/** Role sole-source: clear fallbackModels so runSync cannot retry off-role models. */
export function agentsWithoutFallbacks(agents: AgentLike[], agentName: string): AgentLike[] {
	return agents.map((a) => {
		if (a.name !== agentName) return a;
		const { fallbackModels: _drop, ...rest } = a;
		return { ...rest, name: a.name };
	});
}

function toSingleResult(
	spec: OpsxDispatchSpawnSpec,
	result: OpsxDispatchSingleResult & { exitCode: number; error?: string; finalOutput?: string },
	index: number,
): OpsxDispatchSingleResult {
	return {
		agent: result.agent ?? spec.agent,
		task: result.task ?? spec.task,
		exitCode: result.exitCode,
		error: result.error,
		finalOutput: result.finalOutput,
		messages: result.messages,
		usage: result.usage,
		progress: result.progress
			? { ...result.progress, index, model: result.progress.model ?? spec.model }
			: {
					index,
					agent: spec.agent,
					status: result.exitCode === 0 && !result.error ? "completed" : "failed",
					task: spec.task,
					recentTools: [],
					recentOutput: [],
					toolCount: 0,
					tokens: 0,
					durationMs: 0,
					model: spec.model,
					error: result.error,
				},
		artifactPaths: result.artifactPaths,
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
	},
): Promise<OpsxDispatchSpawnResult> {
	const index = opts.index ?? 0;
	try {
		const { runSync, discoverAgents } = await loadSubagentsApi();
		const { agents: discovered } = discoverAgents(opts.cwd, "both");
		const agents = agentsWithoutFallbacks(discovered, spec.agent);
		const runId = opts.runId ?? `opsx-dispatch-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
		const result = await runSync(opts.cwd, agents, spec.agent, spec.task, {
			runId,
			modelOverride: spec.model,
			cwd: opts.cwd,
			signal: opts.signal,
			index,
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
								.filter((c): c is { type: "text"; text: string } => c.type === "text" && typeof c.text === "string")
								.map((c) => ({ type: "text" as const, text: c.text! })),
							details: {
								mode: "single",
								results: [single],
								progress: single.progress ? [single.progress] : undefined,
							},
						});
					}
				: undefined,
		});
		const ok = result.exitCode === 0 && !result.error;
		const singleResult = toSingleResult(spec, result, index);
		const text =
			result.finalOutput?.trim() ||
			(result.error
				? `spawn error (${spec.model}): ${result.error}`
				: `spawn complete model=${spec.model} agent=${spec.agent} exit=${result.exitCode}`);
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

export type SubagentRenderers = {
	renderSubagentResult: (
		result: { content: unknown; details?: unknown },
		options: { expanded: boolean },
		theme: unknown,
	) => unknown;
	syncResultAnimation: (
		result: { content: unknown; details?: unknown },
		context: { state: Record<string, unknown>; invalidate: () => void },
	) => void;
};

/** Load pi-subagents renderers (result + animation) for opsx_dispatch TUI parity. */
export async function loadSubagentRenderers(): Promise<SubagentRenderers | null> {
	try {
		const renderUrl = pathToFileURL(join(SUBAGENTS_DIR, "render.ts")).href;
		const mod = await import(renderUrl);
		if (typeof mod.renderSubagentResult !== "function") return null;
		return {
			renderSubagentResult: mod.renderSubagentResult,
			syncResultAnimation:
				typeof mod.syncResultAnimation === "function"
					? mod.syncResultAnimation
					: () => {},
		};
	} catch {
		return null;
	}
}

/** @deprecated use loadSubagentRenderers */
export async function loadSubagentRenderResult(): Promise<SubagentRenderers["renderSubagentResult"] | null> {
	const r = await loadSubagentRenderers();
	return r?.renderSubagentResult ?? null;
}
