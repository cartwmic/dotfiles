import { spawn } from "node:child_process";
import { appendFileSync, existsSync, mkdirSync, readFileSync } from "node:fs";
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

/** What asking the coordinator came to: not asked (not a lead session, or not set up), asked and answered (`refusal` is the refusal text when it refused), or asked and failed (why). */
export type Check =
	| { kind: "off" }
	| { kind: "answered"; thread: string; stateDir: string; refusal?: string }
	| { kind: "failed"; thread: string; stateDir: string; reason: string };

/** One line in <state>/t3-hook/turn-end-adapter.jsonl. Best effort: a line that cannot be written never changes the answer. */
export function logLine(stateDir: string, thread: string, cause: "check-failed" | "after-refusal", reason: string, startedAt: number): void {
	try {
		const folder = join(stateDir, "t3-hook");
		mkdirSync(folder, { recursive: true });
		const line = { ts: new Date().toISOString(), adapter: "pi-extension", thread, outcome: "allowed", cause, reason, duration_ms: Date.now() - startedAt };
		appendFileSync(join(folder, "turn-end-adapter.jsonl"), `${JSON.stringify(line)}\n`);
	} catch {
		// nothing to do: the end stands either way
	}
}

/**
 * Asks the coordinator about this end. Never throws. The rule, and every read behind it, is `coordinator t3 turn-end` in the configured coordinator checkout (src/t3-hook/turn-end.ts): this holds no rule, no list of
 * wakers and no T3 reader. It counts nothing but the jobs (`stop_running_jobs.py --count`, the same hook the builder seat's stop uses) and passes the number.
 * Nothing is asked, quietly, when it is not a T3 session or the config is missing or off. Once a thread and an enabled config are there, a check that cannot run (no checkout or state directory, a command that times out,
 * is missing or prints something unreadable) is `failed`, with the reason, and writes its line.
 */
export async function checkTurnEnd(options: { config: TurnEndConfig | undefined; env: NodeJS.ProcessEnv; continued: boolean; run?: Run; startedAt?: number }): Promise<Check> {
	const { config, env } = options;
	const thread = env.T3CODE_THREAD_ID;
	if (!thread || config === undefined || config.enabled === false || !config.coordinatorRepo) return { kind: "off" };
	const startedAt = options.startedAt ?? Date.now();
	const stateDir = env.COORDINATOR_STATE_DIR || config.stateDir;
	if (!stateDir) return { kind: "off" };
	const failed = (reason: string): Check => {
		logLine(stateDir, thread, "check-failed", reason, startedAt);
		return { kind: "failed", thread, stateDir, reason };
	};
	const cli = join(config.coordinatorRepo, "src", "coordinatord", "cli.ts");
	if (!existsSync(cli)) return failed(`coordinator checkout not found: ${cli}`);
	if (!existsSync(stateDir)) return failed(`state directory not found: ${stateDir}`);
	const exec = options.run ?? run;
	const childEnv = { ...env, COORDINATOR_STATE_DIR: stateDir };
	let jobs = 0;
	if (config.jobsHook && existsSync(config.jobsHook)) {
		const counted = await exec("python3", [config.jobsHook, "--count"], { ...childEnv, STOP_JOBS_THREAD: thread }, 10_000);
		const n = Number(counted.stdout.trim());
		if (counted.status === 0 && Number.isInteger(n) && n > 0) jobs = n;
	}
	const done = await exec(
		process.execPath,
		["--experimental-strip-types", "--disable-warning=ExperimentalWarning", cli, "t3", "turn-end", "--thread", thread, "--jobs", String(jobs), ...(options.continued ? ["--continued"] : [])],
		childEnv,
		30_000,
	);
	if (done.status === null) return failed("the command timed out or could not start");
	let parsed: { answer?: unknown; message?: unknown };
	try {
		parsed = JSON.parse(done.stdout.trim().split("\n").pop() ?? "") as { answer?: unknown; message?: unknown };
	} catch {
		return failed(`no readable answer (exit ${done.status})`);
	}
	if (typeof parsed.answer !== "string") return failed(`no readable answer (exit ${done.status})`);
	const refusal = parsed.answer === "refuse" && typeof parsed.message === "string" && parsed.message !== "" ? parsed.message : undefined;
	return { kind: "answered", thread, stateDir, ...(refusal !== undefined ? { refusal } : {}) };
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

/**
 * The two handlers, with what they read (config, environment, the runner) passed in so a test can drive them.
 * A refusal goes out at most once per user turn. `refusedText` is the refusal this turn has had; only a real user input clears it: an input that is the extension's own follow-up (`source: "extension"`) or that carries the
 * refusal text itself never does. While it is set, the coordinator is still asked, with `--continued`, so the let-through is reported, but a refusal in its answer is not sent: the end is allowed and a line says so.
 */
export function register(pi: Pick<ExtensionAPI, "on" | "sendUserMessage">, deps: { config: TurnEndConfig | undefined; env: NodeJS.ProcessEnv; run?: Run }): void {
	let refusedText: string | undefined;
	let asking = false;
	pi.on("input", async (event: { source?: string; text?: string }) => {
		if (event.source !== "extension" && event.text !== refusedText) refusedText = undefined;
		return { action: "continue" as const };
	});
	pi.on("agent_end", async (event: { messages?: unknown }) => {
		if (lastStopReason(event.messages) !== "stop" || asking) return;
		asking = true;
		try {
			const startedAt = Date.now();
			const check = await checkTurnEnd({ config: deps.config, env: deps.env, continued: refusedText !== undefined, run: deps.run, startedAt });
			if (check.kind !== "answered" || check.refusal === undefined) return;
			if (refusedText !== undefined) {
				logLine(check.stateDir, check.thread, "after-refusal", "the coordinator refused an end that already followed a refusal", startedAt);
				return;
			}
			refusedText = check.refusal;
			pi.sendUserMessage(check.refusal, { deliverAs: "followUp" });
		} finally {
			asking = false;
		}
	});
}

/**
 * A lead's turn may end only when something will wake it, an ask that names it is open, or a state note was accepted (the lead turn-end check, `coordinator t3 turn-end`). When the coordinator refuses the end, the refusal
 * goes back to the lead as a follow-up message and the next turn starts. The next end, once that follow-up has run, is asked again with `--continued`: the coordinator then lets it through and reports it. The refusal is not
 * sent twice in one user turn, whatever the coordinator answers; only a real user input starts a new turn.
 */
export default function (pi: ExtensionAPI) {
	register(pi, { config: loadConfig(join(dirname(fileURLToPath(import.meta.url)), "config.json")), env: process.env });
}
