import { readFileSync, renameSync, writeFileSync } from "node:fs";

export const CHECK_POINTS = ["turn_end", "agent_end"] as const;
export type CheckPoint = (typeof CHECK_POINTS)[number];

/** Default follow-up sent after mid-turn compaction aborts the active agent run. */
export const DEFAULT_CONTINUATION = "Continue from where you left off.";

export interface AutoCompactConfig {
	enabled: boolean;
	thresholdPercent: number;
	checkAt: CheckPoint[];
	/**
	 * Follow-up injected after mid-turn (`turn_end`) compaction.
	 * `false` disables resume. Agent-end compaction never auto-continues
	 * (the run already finished).
	 */
	continuation: string | false;
}

export interface ContextUsage {
	tokens: number;
	contextWindow: number;
}

export const DEFAULT_CONFIG: AutoCompactConfig = {
	enabled: true,
	thresholdPercent: 40,
	checkAt: ["turn_end", "agent_end"],
	continuation: DEFAULT_CONTINUATION,
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
	const configuredPoints = Array.isArray(raw.checkAt) ? raw.checkAt.filter(isCheckPoint) : [];
	const checkAt = CHECK_POINTS.filter((point) => configuredPoints.includes(point));

	return {
		enabled: typeof raw.enabled === "boolean" ? raw.enabled : DEFAULT_CONFIG.enabled,
		thresholdPercent,
		checkAt: checkAt.length > 0 ? checkAt : [...DEFAULT_CONFIG.checkAt],
		continuation: "continuation" in raw ? normalizeContinuation(raw.continuation) : DEFAULT_CONTINUATION,
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

export function thresholdTokens(contextWindow: number, thresholdPercent: number): number | undefined {
	if (!Number.isFinite(contextWindow) || contextWindow <= 0) return undefined;
	if (!Number.isFinite(thresholdPercent) || thresholdPercent <= 0 || thresholdPercent > 100) return undefined;
	return Math.ceil((thresholdPercent / 100) * contextWindow);
}

export function shouldTrigger(
	config: AutoCompactConfig,
	checkPoint: CheckPoint,
	usage: ContextUsage | undefined,
	lastAttemptTokens?: number,
): boolean {
	if (!config.enabled || !config.checkAt.includes(checkPoint) || !usage) return false;
	const threshold = thresholdTokens(usage.contextWindow, config.thresholdPercent);
	if (threshold === undefined || !Number.isFinite(usage.tokens) || usage.tokens < threshold) return false;
	return lastAttemptTokens === undefined || usage.tokens > lastAttemptTokens;
}

/** Resume text for mid-turn compaction, or undefined when resume is off / not applicable. */
export function resumeAfterCompact(config: AutoCompactConfig, checkPoint: CheckPoint): string | undefined {
	if (checkPoint !== "turn_end") return undefined;
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
	return `auto-compaction ${config.enabled ? "ON" : "OFF"}; threshold ${config.thresholdPercent}%; check at ${points}; continuation ${describeContinuation(config.continuation)}`;
}
