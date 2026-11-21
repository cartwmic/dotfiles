import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

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

/** The coordinator's `helperGateReason` (src/coordinator-session/helper-gate.ts): the reason to block the call, or undefined to let it run. */
export type HelperGate = (call: HelperCall, env: NodeJS.ProcessEnv, stateDir: string) => string | undefined;

/** Loads the coordinator's gate from its file, or undefined when the file does not hold one. Throws when the file cannot be loaded. */
export type LoadGate = (file: string) => Promise<HelperGate | undefined>;

export const loadGate: LoadGate = async (file) => {
	const loaded = (await import(pathToFileURL(file).href)) as { helperGateReason?: unknown };
	return typeof loaded.helperGateReason === "function" ? (loaded.helperGateReason as HelperGate) : undefined;
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

/**
 * The reason to block the call, or undefined to let it run. Never throws. The decision, and the work of asking the hook, is the coordinator's own `helperGateReason`
 * (src/coordinator-session/helper-gate.ts in the configured checkout), loaded when first needed: this holds no model list, seat table, rule text or hook launcher.
 * It lets the call through, quietly, when the config is missing or off, the checkout, its helper-gate.ts or its state directory is not there, the process is the coordinator's
 * own session, or the file cannot be loaded. Past that point the coordinator's code fails open and logs for itself.
 */
export async function gateReason(call: HelperCall, options: { config: GateConfig | undefined; env: NodeJS.ProcessEnv; argv: readonly string[]; load?: LoadGate }): Promise<string | undefined> {
	const { config, env } = options;
	if (config === undefined || config.enabled === false || !config.coordinatorRepo) return undefined;
	if (loadsCoordinatorSession(options.argv)) return undefined;
	const file = join(config.coordinatorRepo, "src", "coordinator-session", "helper-gate.ts");
	const stateDir = env.COORDINATOR_STATE_DIR || config.stateDir;
	if (!stateDir || !existsSync(file) || !existsSync(stateDir)) return undefined;
	try {
		const gate = await (options.load ?? loadGate)(file);
		return gate?.(call, env, stateDir);
	} catch {
		return undefined;
	}
}

/** What the handler reads of Pi's tool call and context. */
interface PiToolCall { toolName: string; toolCallId: string; input: unknown }
interface PiContext { cwd: string; sessionManager: { getSessionId(): string }; model?: { provider: string; id: string } | undefined }

/** The `tool_call` handler: blocks a refused `subagent` call with the coordinator's reason. */
export const toolCallHandler =
	(options: { config: GateConfig | undefined; env: NodeJS.ProcessEnv; argv: readonly string[]; load?: LoadGate }) =>
	async (event: PiToolCall, ctx: PiContext) => {
		const reason = await gateReason(
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
