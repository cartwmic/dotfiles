/**
 * Config + runtime-toggle loading for the hindsight pi extension.
 *
 * Layered (later wins): DEFAULTS -> config.json (beside this module) ->
 * a small allowlist of env overrides. The on/off runtime toggle lives in a
 * sidecar state.json that is NOT chezmoi-managed, so live `/hindsight off`
 * never drifts the chezmoi source.
 */
import * as fs from "node:fs";
import * as path from "node:path";

export type RecallBudget = "low" | "mid" | "high";

export interface HindsightConfig {
	/** Base REST URL, no trailing slash, e.g. https://hindsight-api.internal.cartwmic.com */
	apiUrl: string;
	/** Memory bank id (path-pinned bank). */
	bankId: string;
	/** Bearer token. Empty string = no auth (current homelab state). */
	apiToken: string;

	autoRecall: boolean;
	autoRetain: boolean;

	recallBudget: RecallBudget;
	recallMaxTokens: number;
	recallTypes: string[];
	recallMaxQueryChars: number;

	/** Ship a full-session retain every N agent loops (response cycles). */
	retainEveryNTurns: number;
	/** Also retain a final time when the session shuts down. */
	retainOnSessionEnd: boolean;
	retainRoles: string[];
	retainToolCalls: boolean;

	requestTimeoutMs: number;
	/** Default on/off, from config.json. Overridden at runtime by state.json. */
	enabled: boolean;
	debug: boolean;
}

export const DEFAULTS: HindsightConfig = {
	apiUrl: "https://hindsight-api.internal.cartwmic.com",
	bankId: "cartwmic",
	apiToken: "",
	autoRecall: true,
	autoRetain: true,
	recallBudget: "mid",
	recallMaxTokens: 1024,
	recallTypes: ["observation"],
	recallMaxQueryChars: 800,
	retainEveryNTurns: 10,
	retainOnSessionEnd: true,
	retainRoles: ["user", "assistant"],
	retainToolCalls: false,
	requestTimeoutMs: 12000,
	enabled: true,
	debug: false,
};

const STATE_FILE = "state.json";

function asBudget(v: unknown, fallback: RecallBudget): RecallBudget {
	return v === "low" || v === "mid" || v === "high" ? v : fallback;
}
function asStringArray(v: unknown, fallback: string[]): string[] {
	return Array.isArray(v) && v.every((x) => typeof x === "string") ? (v as string[]) : fallback;
}
function asPosInt(v: unknown, fallback: number): number {
	return typeof v === "number" && Number.isFinite(v) && v >= 0 ? Math.floor(v) : fallback;
}
function asBool(v: unknown, fallback: boolean): boolean {
	return typeof v === "boolean" ? v : fallback;
}
function asString(v: unknown, fallback: string): string {
	return typeof v === "string" ? v : fallback;
}

/** Parse raw config.json content over DEFAULTS. Pure; takes the file text. */
export function parseConfig(raw: string | undefined): HindsightConfig {
	let p: Partial<Record<keyof HindsightConfig, unknown>> = {};
	if (raw) {
		try {
			p = JSON.parse(raw) as typeof p;
		} catch {
			p = {};
		}
	}
	return {
		apiUrl: asString(p.apiUrl, DEFAULTS.apiUrl).replace(/\/+$/, ""),
		bankId: asString(p.bankId, DEFAULTS.bankId),
		apiToken: asString(p.apiToken, DEFAULTS.apiToken),
		autoRecall: asBool(p.autoRecall, DEFAULTS.autoRecall),
		autoRetain: asBool(p.autoRetain, DEFAULTS.autoRetain),
		recallBudget: asBudget(p.recallBudget, DEFAULTS.recallBudget),
		recallMaxTokens: asPosInt(p.recallMaxTokens, DEFAULTS.recallMaxTokens),
		recallTypes: asStringArray(p.recallTypes, DEFAULTS.recallTypes),
		recallMaxQueryChars: asPosInt(p.recallMaxQueryChars, DEFAULTS.recallMaxQueryChars),
		retainEveryNTurns: Math.max(1, asPosInt(p.retainEveryNTurns, DEFAULTS.retainEveryNTurns)),
		retainOnSessionEnd: asBool(p.retainOnSessionEnd, DEFAULTS.retainOnSessionEnd),
		retainRoles: asStringArray(p.retainRoles, DEFAULTS.retainRoles),
		retainToolCalls: asBool(p.retainToolCalls, DEFAULTS.retainToolCalls),
		requestTimeoutMs: asPosInt(p.requestTimeoutMs, DEFAULTS.requestTimeoutMs),
		enabled: asBool(p.enabled, DEFAULTS.enabled),
		debug: asBool(p.debug, DEFAULTS.debug),
	};
}

/** A small allowlist of env overrides applied on top of parsed config. */
export function applyEnvOverrides(cfg: HindsightConfig, env: NodeJS.ProcessEnv): HindsightConfig {
	const out = { ...cfg };
	if (env.HINDSIGHT_API_URL) out.apiUrl = env.HINDSIGHT_API_URL.replace(/\/+$/, "");
	if (env.HINDSIGHT_API_TOKEN !== undefined) out.apiToken = env.HINDSIGHT_API_TOKEN;
	if (env.HINDSIGHT_BANK_ID) out.bankId = env.HINDSIGHT_BANK_ID;
	if (env.HINDSIGHT_AUTO_RECALL === "false") out.autoRecall = false;
	if (env.HINDSIGHT_AUTO_RETAIN === "false") out.autoRetain = false;
	if (env.HINDSIGHT_DEBUG === "true") out.debug = true;
	return out;
}

/** Read config.json beside this module, merge env. Missing -> DEFAULTS. */
export function loadConfig(dir: string, env: NodeJS.ProcessEnv = process.env): HindsightConfig {
	let raw: string | undefined;
	try {
		raw = fs.readFileSync(path.join(dir, "config.json"), "utf8");
	} catch {
		raw = undefined;
	}
	return applyEnvOverrides(parseConfig(raw), env);
}

/** Effective on/off: runtime override in state.json wins over config default. */
export function loadEnabled(dir: string, configDefault: boolean): boolean {
	try {
		const parsed = JSON.parse(fs.readFileSync(path.join(dir, STATE_FILE), "utf8")) as {
			enabled?: unknown;
		};
		if (typeof parsed.enabled === "boolean") return parsed.enabled;
	} catch {
		/* no override */
	}
	return configDefault;
}

/** Persist the runtime on/off override to the sidecar state.json. */
export function saveEnabled(dir: string, value: boolean): void {
	fs.writeFileSync(path.join(dir, STATE_FILE), `${JSON.stringify({ enabled: value }, null, 2)}\n`);
}
