/**
 * Library spawn adapter: opsx-loop → pi-subagents runSync (one-way; OPSX-blind).
 * (opsx-loop.dispatch-spawns-via-subagent-library)
 */
import { join } from "node:path";
import { homedir } from "node:os";
import { pathToFileURL } from "node:url";
import type { OpsxDispatchSpawnResult, OpsxDispatchSpawnSpec } from "./helpers.ts";

const SUBAGENTS_DIR = join(homedir(), ".pi", "agent", "git", "github.com", "cartwmic", "pi-subagents");

type RunSyncFn = (
	runtimeCwd: string,
	agents: Array<{ name: string }>,
	agentName: string,
	task: string,
	options: { runId: string; modelOverride?: string; cwd?: string; signal?: AbortSignal },
) => Promise<{ exitCode: number; error?: string; messages?: unknown[] }>;

type DiscoverFn = (cwd: string, scope: "user" | "project" | "both") => { agents: Array<{ name: string }> };

async function loadSubagentsApi(): Promise<{ runSync: RunSyncFn; discoverAgents: DiscoverFn }> {
	const executionUrl = pathToFileURL(join(SUBAGENTS_DIR, "execution.ts")).href;
	const agentsUrl = pathToFileURL(join(SUBAGENTS_DIR, "agents.ts")).href;
	const [execution, agents] = await Promise.all([import(executionUrl), import(agentsUrl)]);
	return {
		runSync: execution.runSync as RunSyncFn,
		discoverAgents: agents.discoverAgents as DiscoverFn,
	};
}

/** Default production spawn: pi-subagents runSync with forced modelOverride. */
export async function spawnViaRunSync(
	spec: OpsxDispatchSpawnSpec,
	opts: { cwd: string; signal?: AbortSignal; runId?: string },
): Promise<OpsxDispatchSpawnResult> {
	try {
		const { runSync, discoverAgents } = await loadSubagentsApi();
		const { agents } = discoverAgents(opts.cwd, "both");
		const runId = opts.runId ?? `opsx-dispatch-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
		const result = await runSync(opts.cwd, agents, spec.agent, spec.task, {
			runId,
			modelOverride: spec.model,
			cwd: opts.cwd,
			signal: opts.signal,
		});
		const ok = result.exitCode === 0 && !result.error;
		const text = result.error
			? `spawn error (${spec.model}): ${result.error}`
			: `spawn complete model=${spec.model} agent=${spec.agent} exit=${result.exitCode}`;
		return { model: spec.model, agent: spec.agent, ok, text };
	} catch (e: unknown) {
		const msg = e instanceof Error ? e.message : String(e);
		return {
			model: spec.model,
			agent: spec.agent,
			ok: false,
			text: `opsx_dispatch spawn failed to load pi-subagents runSync: ${msg}`,
		};
	}
}
