import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

/** What config.json (rendered per profile from config.json.tmpl) says: the coordinator checkout and its state directory, and the hook that counts this session's running jobs. */
export interface TurnEndConfig {
	enabled?: boolean;
	coordinatorRepo?: string;
	stateDir?: string;
	jobsHook?: string;
}

/** Runs a command and gives its exit status and stdout; never rejects (a spawn error or a timeout is a null status). */
export type Run = (command: string, args: readonly string[], env: NodeJS.ProcessEnv, timeoutMs: number) => Promise<{ status: number | null; stdout: string }>;

export const run: Run = (command, args, env, timeoutMs) =>
	new Promise((resolve) => {
		let stdout = "";
		let settled = false;
		const done = (status: number | null): void => {
			if (settled) return;
			settled = true;
			clearTimeout(timer);
			resolve({ status, stdout });
		};
		const child = spawn(command, [...args], { env, stdio: ["ignore", "pipe", "ignore"] });
		const timer = setTimeout(() => {
			child.kill("SIGKILL");
			done(null);
		}, timeoutMs);
		child.stdout.setEncoding("utf8");
		child.stdout.on("data", (chunk: string) => {
			stdout += chunk;
		});
		child.on("error", () => done(null));
		child.on("close", (code) => done(code));
	});

/** The config beside the extension, or undefined when it is missing or unreadable. */
export function loadConfig(path: string): TurnEndConfig | undefined {
	try {
		const parsed: unknown = JSON.parse(readFileSync(path, "utf8"));
		return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed) ? (parsed as TurnEndConfig) : undefined;
	} catch {
		return undefined;
	}
}

/**
 * The coordinator's answer for this end: the refusal text, or undefined to let the end stand. Never throws. The rule, and every read behind it, is `coordinator t3 turn-end` in the configured coordinator checkout
 * (src/t3-hook/turn-end.ts): this holds no rule, no list of wakers and no T3 reader. It counts nothing but the jobs (`stop_running_jobs.py --count`, the same hook the builder seat's stop uses) and passes the number.
 * It lets the end stand, quietly, when it is not a T3 session, the config is missing or off, the checkout or state directory is not there, or the command gives no answer.
 */
export async function turnEndRefusal(options: { config: TurnEndConfig | undefined; env: NodeJS.ProcessEnv; continued: boolean; run?: Run }): Promise<string | undefined> {
	const { config, env } = options;
	const thread = env.T3CODE_THREAD_ID;
	if (!thread || config === undefined || config.enabled === false || !config.coordinatorRepo) return undefined;
	const cli = join(config.coordinatorRepo, "src", "coordinatord", "cli.ts");
	const stateDir = env.COORDINATOR_STATE_DIR || config.stateDir;
	if (!stateDir || !existsSync(cli) || !existsSync(stateDir)) return undefined;
	const exec = options.run ?? run;
	const childEnv = { ...env, COORDINATOR_STATE_DIR: stateDir };
	let jobs = 0;
	if (config.jobsHook && existsSync(config.jobsHook)) {
		const counted = await exec("python3", [config.jobsHook, "--count"], { ...childEnv, STOP_JOBS_THREAD: thread }, 10_000);
		const n = Number(counted.stdout.trim());
		if (counted.status === 0 && Number.isInteger(n) && n > 0) jobs = n;
	}
	const answer = await exec(
		process.execPath,
		["--experimental-strip-types", "--disable-warning=ExperimentalWarning", cli, "t3", "turn-end", "--thread", thread, "--jobs", String(jobs), ...(options.continued ? ["--continued"] : [])],
		childEnv,
		30_000,
	);
	try {
		const parsed = JSON.parse(answer.stdout.trim().split("\n").pop() ?? "") as { answer?: unknown; message?: unknown };
		return parsed.answer === "refuse" && typeof parsed.message === "string" && parsed.message !== "" ? parsed.message : undefined;
	} catch {
		return undefined;
	}
}

/** The stop reason of the last assistant message of an `agent_end` event, or undefined. Only a clean end ("stop") is looked at: an abort or an error is not a lead ending its turn on a promise. */
export function lastStopReason(messages: unknown): string | undefined {
	if (!Array.isArray(messages)) return undefined;
	for (let i = messages.length - 1; i >= 0; i--) {
		const m = messages[i] as { role?: unknown; stopReason?: unknown } | undefined;
		if (m?.role === "assistant") return typeof m.stopReason === "string" ? m.stopReason : undefined;
	}
	return undefined;
}

/** The two handlers, with what they read (config, environment, the runner) passed in so a test can drive them. */
export function register(pi: Pick<ExtensionAPI, "on" | "sendUserMessage">, deps: { config: TurnEndConfig | undefined; env: NodeJS.ProcessEnv; run?: Run }): void {
	let refused = false;
	pi.on("input", async (event: { source?: string }) => {
		if (event.source !== "extension") refused = false;
		return { action: "continue" as const };
	});
	pi.on("agent_end", async (event: { messages?: unknown }) => {
		if (lastStopReason(event.messages) !== "stop") return;
		const message = await turnEndRefusal({ config: deps.config, env: deps.env, continued: refused, run: deps.run });
		refused = message !== undefined;
		if (message !== undefined) pi.sendUserMessage(message, { deliverAs: "followUp" });
	});
}

/**
 * A lead's turn may end only when something will wake it, an ask that names it is open, or a state note was accepted (the lead turn-end check, `coordinator t3 turn-end`). When the coordinator refuses the end, the refusal
 * goes back to the lead as a follow-up message and the next turn starts. The next end, once that follow-up has run, is asked again with `--continued`: the coordinator then lets it through and reports it. The flag is this process's own and is
 * cleared by any input that is not our follow-up, so a new request from the coordinator or Michael starts again from a first end.
 */
export default function (pi: ExtensionAPI) {
	register(pi, { config: loadConfig(join(dirname(fileURLToPath(import.meta.url)), "config.json")), env: process.env });
}
