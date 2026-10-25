import { readFileSync, renameSync, writeFileSync } from "node:fs";

export const CHECK_POINTS = ["turn_end", "agent_end"] as const;
export type CheckPoint = (typeof CHECK_POINTS)[number];

/** Default follow-up sent after mid-turn compaction aborts the active agent run. */
export const DEFAULT_CONTINUATION = "Continue from where you left off.";

export interface AutoCompactConfig {
	enabled: boolean;
	thresholdPercent: number;
	/**
	 * Absolute cap in tokens. Compaction fires at whichever comes first: thresholdPercent of the model's context
	 * window or this many tokens. A flat low percentage would compact small-window models far too early.
	 */
	thresholdTokens: number;
	checkAt: CheckPoint[];
	/**
	 * Follow-up injected after inter-turn (`turn_end`) compaction.
	 * `false` disables resume. Final-turn and agent-end compactions never
	 * auto-continue (the run already finished).
	 */
	continuation: string | false;
	/**
	 * Circuit breaker: after this many consecutive compactions that fail to
	 * bring context back below threshold, auto-compaction pauses for the rest of
	 * the session (prevents compaction loops when a provider's compaction does
	 * not reduce context). Provider-agnostic; well-behaved providers reduce
	 * reliably so the breaker never trips. Minimum 1.
	 */
	maxIneffectiveCompactions: number;
	/**
	 * Seconds the tripped breaker waits before one retry. Each consecutive trip doubles the wait (capped at
	 * MAX_BREAKER_COOLDOWN_SECONDS); a below-threshold reading resets it. 0 keeps the old behavior: pause for the
	 * rest of the session (until /auto-compact reload or a new session).
	 */
	breakerCooldownSeconds: number;
}

export const MAX_BREAKER_COOLDOWN_SECONDS = 3600;

export interface ContextUsage {
	tokens: number;
	contextWindow: number;
}

export const DEFAULT_CONFIG: AutoCompactConfig = {
	enabled: true,
	thresholdPercent: 40,
	thresholdTokens: 200_000,
	checkAt: ["turn_end", "agent_end"],
	continuation: DEFAULT_CONTINUATION,
	maxIneffectiveCompactions: 2,
	breakerCooldownSeconds: 300,
};

function isCheckPoint(value: unknown): value is CheckPoint {
	return typeof value === "string" && CHECK_POINTS.includes(value as CheckPoint);
}

export function normalizeContinuation(value: unknown): string | false {
	if (value === false) return false;
	if (typeof value !== "string") return DEFAULT_CONTINUATION;
	const trimmed = value.trim();
	return trimmed.length > 0 ? trimmed : false;
}

export function normalizeConfig(value: unknown): AutoCompactConfig {
	const raw = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
	const threshold = raw.thresholdPercent;
	const thresholdPercent =
		typeof threshold === "number" && Number.isFinite(threshold) && threshold > 0 && threshold <= 100
			? threshold
			: DEFAULT_CONFIG.thresholdPercent;
	const cap = raw.thresholdTokens;
	const thresholdTokens =
		typeof cap === "number" && Number.isFinite(cap) && cap >= 1 ? Math.floor(cap) : DEFAULT_CONFIG.thresholdTokens;
	const configuredPoints = Array.isArray(raw.checkAt) ? raw.checkAt.filter(isCheckPoint) : [];
	const checkAt = CHECK_POINTS.filter((point) => configuredPoints.includes(point));
	const rawMax = raw.maxIneffectiveCompactions;
	const maxIneffectiveCompactions =
		typeof rawMax === "number" && Number.isFinite(rawMax) && rawMax >= 1
			? Math.floor(rawMax)
			: DEFAULT_CONFIG.maxIneffectiveCompactions;

	const rawCooldown = raw.breakerCooldownSeconds;
	const breakerCooldownSeconds =
		typeof rawCooldown === "number" && Number.isFinite(rawCooldown) && rawCooldown >= 0
			? Math.floor(rawCooldown)
			: DEFAULT_CONFIG.breakerCooldownSeconds;

	return {
		enabled: typeof raw.enabled === "boolean" ? raw.enabled : DEFAULT_CONFIG.enabled,
		thresholdPercent,
		thresholdTokens,
		checkAt: checkAt.length > 0 ? checkAt : [...DEFAULT_CONFIG.checkAt],
		continuation: "continuation" in raw ? normalizeContinuation(raw.continuation) : DEFAULT_CONTINUATION,
		maxIneffectiveCompactions,
		breakerCooldownSeconds,
	};
}

export function loadConfig(path: string): AutoCompactConfig {
	try {
		return normalizeConfig(JSON.parse(readFileSync(path, "utf8")));
	} catch {
		return { ...DEFAULT_CONFIG, checkAt: [...DEFAULT_CONFIG.checkAt] };
	}
}

export function saveConfig(path: string, config: AutoCompactConfig): void {
	const normalized = normalizeConfig(config);
	const temporaryPath = `${path}.${process.pid}.tmp`;
	writeFileSync(temporaryPath, `${JSON.stringify(normalized, null, 2)}\n`, { mode: 0o644 });
	renameSync(temporaryPath, path);
}

/** Tokens at which compaction fires: the percentage of the window, or capTokens when that is lower. */
export function thresholdTokens(contextWindow: number, thresholdPercent: number, capTokens?: number): number | undefined {
	if (!Number.isFinite(contextWindow) || contextWindow <= 0) return undefined;
	if (!Number.isFinite(thresholdPercent) || thresholdPercent <= 0 || thresholdPercent > 100) return undefined;
	const byPercent = Math.ceil((thresholdPercent / 100) * contextWindow);
	return capTokens !== undefined && Number.isFinite(capTokens) && capTokens >= 1 ? Math.min(byPercent, capTokens) : byPercent;
}

/** Wait before the next breaker retry: base doubled per consecutive trip, capped. undefined = never retry. */
export function breakerCooldownMs(baseSeconds: number, consecutiveTrips: number): number | undefined {
	if (!(baseSeconds > 0)) return undefined;
	const seconds = Math.min(baseSeconds * 2 ** Math.max(0, consecutiveTrips - 1), MAX_BREAKER_COOLDOWN_SECONDS);
	return seconds * 1000;
}

export function shouldTrigger(
	config: AutoCompactConfig,
	checkPoint: CheckPoint,
	usage: ContextUsage | undefined,
	lastAttemptTokens?: number,
): boolean {
	if (!config.enabled || !config.checkAt.includes(checkPoint) || !usage) return false;
	const threshold = thresholdTokens(usage.contextWindow, config.thresholdPercent, config.thresholdTokens);
	if (threshold === undefined || !Number.isFinite(usage.tokens) || usage.tokens < threshold) return false;
	return lastAttemptTokens === undefined || usage.tokens > lastAttemptTokens;
}

/** Resume text when compaction interrupts an agent between turns. */
export function resumeAfterCompact(
	config: AutoCompactConfig,
	checkPoint: CheckPoint,
	agentWillContinue: boolean,
): string | undefined {
	if (checkPoint !== "turn_end" || !agentWillContinue) return undefined;
	if (config.continuation === false) return undefined;
	return config.continuation;
}

export function describeContinuation(continuation: string | false): string {
	if (continuation === false) return "OFF";
	const preview = continuation.length > 48 ? `${continuation.slice(0, 45)}...` : continuation;
	return `"${preview}"`;
}

export function describeConfig(config: AutoCompactConfig): string {
	const points = config.checkAt.join(" + ");
	return `auto-compaction ${config.enabled ? "ON" : "OFF"}; threshold ${config.thresholdPercent}% or ${config.thresholdTokens.toLocaleString("en-US")} tokens, whichever is lower; check at ${points}; continuation ${describeContinuation(config.continuation)}; breaker ${config.maxIneffectiveCompactions}, ${config.breakerCooldownSeconds > 0 ? `retry after ${config.breakerCooldownSeconds}s (doubling)` : "no retry"}`;
}
