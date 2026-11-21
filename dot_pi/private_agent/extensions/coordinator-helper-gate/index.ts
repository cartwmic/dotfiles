import { spawnSync } from "node:child_process";
import { appendFileSync, existsSync, mkdirSync, readFileSync } from "node:fs";
import { basename, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

/** pi-subagents' helper tool. Every other tool passes through untouched. */
export const HELPER_TOOL = "subagent";

const NODE_FLAGS = ["--experimental-strip-types", "--disable-warning=ExperimentalWarning"];
const HOOK_TIMEOUT_MS = 30_000;

/** What config.json (rendered per profile from config.json.tmpl) says: where the coordinator checkout and its state directory are. */
export interface GateConfig {
	enabled?: boolean;
	coordinatorRepo?: string;
	stateDir?: string;
}

/** What the gate needs of a Pi tool call and its session. */
export interface HelperCall {
	toolName: string;
	toolCallId: string;
	input: unknown;
	cwd: string;
	sessionId: string;
	/** The session's model as `provider/id`, when it has one. */
	model: string | undefined;
}

/** Starts the hook for one call: its stdout, or `failure` when it could not run. */
export type RunHook = (hook: string, stdin: string, env: NodeJS.ProcessEnv) => { stdout: string; failure?: string };

/** The node that starts the hook: Pi's own when it is a node, else the one on PATH. */
const nodeCommand = (): string => (/^node(\.exe)?$/.test(basename(process.execPath)) ? process.execPath : "node");

export const runHook: RunHook = (hook, stdin, env) => {
	const run = spawnSync(nodeCommand(), [...NODE_FLAGS, hook, "--pi"], { input: stdin, env, encoding: "utf8", timeout: HOOK_TIMEOUT_MS });
	if (run.error !== undefined) return { stdout: "", failure: run.error.message };
	if (run.status !== 0) return { stdout: "", failure: `exit ${run.status ?? run.signal}: ${run.stderr.trim().split("\n")[0] ?? ""}` };
	return { stdout: run.stdout };
};

/** The config beside the extension, or undefined when it is missing or unreadable. */
export function loadConfig(path: string): GateConfig | undefined {
	try {
		const parsed: unknown = JSON.parse(readFileSync(path, "utf8"));
		return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed) ? (parsed as GateConfig) : undefined;
	} catch {
		return undefined;
	}
}

/**
 * Whether this Pi process was started with the coordinator's own session extension (`-e <repo>/src/coordinator-session/index.ts`, how the daemon launches its Pi).
 * That extension already runs the gate on every `subagent` call, so this one stands down there instead of asking twice.
 */
export function loadsCoordinatorSession(argv: readonly string[]): boolean {
	const isSession = (path: string | undefined): boolean => path !== undefined && /(^|[\\/])coordinator-session[\\/]index\.ts$/.test(path);
	return argv.some((arg, i) => {
		if (arg === "-e" || arg === "--extension") return isSession(argv[i + 1]);
		return arg.startsWith("--extension=") && isSession(arg.slice("--extension=".length));
	});
}

const isObject = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);

/** Adds one line to <state>/t3-hook/helper-gate.log, the coordinator's own record of a gate that could not run. Never throws. The caller has checked that the state directory exists, so this never makes one. */
function logSkip(stateDir: string, call: HelperCall, why: string): void {
	try {
		const input = isObject(call.input) ? call.input : {};
		const file = join(stateDir, "t3-hook", "helper-gate.log");
		mkdirSync(dirname(file), { recursive: true });
		appendFileSync(file, `${JSON.stringify({ at: new Date().toISOString(), session: call.sessionId, call: call.toolCallId, kind: input.agent ?? null, model: input.model ?? null, what: `skipped: the gate could not run (${why})` })}\n`);
	} catch {
		/* the gate fails open */
	}
}

/**
 * The reason to block the call, or undefined to let it run. Never throws. The decision is the coordinator's (`hook.ts --pi`): this holds no model list, seat table or rule text.
 * It lets the call through, quietly, when the config is missing or off, the checkout or its state directory is not there, the process is the coordinator's own session,
 * or the hook cannot run or answers with something unreadable (the last two add a line to the coordinator's helper-gate log).
 */
export function gateReason(call: HelperCall, options: { config: GateConfig | undefined; env: NodeJS.ProcessEnv; argv: readonly string[]; run?: RunHook }): string | undefined {
	if (call.toolName !== HELPER_TOOL) return undefined;
	const { config, env } = options;
	if (config === undefined || config.enabled === false || !config.coordinatorRepo) return undefined;
	if (loadsCoordinatorSession(options.argv)) return undefined;
	const hook = join(config.coordinatorRepo, "src", "t3-hook", "hook.ts");
	const stateDir = env.COORDINATOR_STATE_DIR || config.stateDir;
	if (!stateDir || !existsSync(hook) || !existsSync(stateDir)) return undefined;
	const skipped = (why: string): undefined => {
		logSkip(stateDir, call, why);
		return undefined;
	};
	try {
		const stdin = JSON.stringify({ session_id: call.sessionId, tool_use_id: call.toolCallId, cwd: call.cwd, session_model: call.model, tool_input: call.input });
		const answered = (options.run ?? runHook)(hook, stdin, { ...env, COORDINATOR_STATE_DIR: stateDir });
		if (answered.failure !== undefined) return skipped(answered.failure);
		if (answered.stdout.trim() === "") return undefined;
		const answer = JSON.parse(answered.stdout) as { block?: unknown; reason?: unknown };
		return answer.block === true && typeof answer.reason === "string" ? answer.reason : skipped("its answer was not a refusal it could read");
	} catch (error) {
		return skipped((error as Error).message.split("\n")[0] ?? "error");
	}
}

/** What the handler reads of Pi's tool call and context. */
interface PiToolCall { toolName: string; toolCallId: string; input: unknown }
interface PiContext { cwd: string; sessionManager: { getSessionId(): string }; model?: { provider: string; id: string } | undefined }

/** The `tool_call` handler: blocks a refused `subagent` call with the coordinator's reason. */
export const toolCallHandler =
	(options: { config: GateConfig | undefined; env: NodeJS.ProcessEnv; argv: readonly string[]; run?: RunHook }) =>
	async (event: PiToolCall, ctx: PiContext) => {
		const reason = gateReason(
			{ toolName: event.toolName, toolCallId: event.toolCallId, input: event.input, cwd: ctx.cwd, sessionId: ctx.sessionManager.getSessionId(), model: ctx.model ? `${ctx.model.provider}/${ctx.model.id}` : undefined },
			options,
		);
		return reason === undefined ? undefined : { block: true as const, reason };
	};

/**
 * Runs the coordinator's helper gate on this Pi session's `subagent` calls: a helper that would run on a model stronger than Haiku 5.5, with no `Seat:` first line
 * that declares it, is blocked. Sessions T3 starts on the `pi` and `pi-lead` instances, and Pi sessions opened in a terminal, load it from the global extensions.
 */
export default function (pi: ExtensionAPI) {
	const config = loadConfig(join(dirname(fileURLToPath(import.meta.url)), "config.json"));
	pi.on("tool_call", toolCallHandler({ config, env: process.env, argv: process.argv }));
}
