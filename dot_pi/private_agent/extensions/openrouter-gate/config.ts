import { readFileSync, renameSync, writeFileSync } from "node:fs";

export const DEFAULT_ALLOWED_MODELS = ["z-ai/glm-5.3-flash"] as const;
export const OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1";

export interface OpenRouterGateConfig {
	/** Persistent provider toggle. Written by `/openrouter on|off`. */
	enabled: boolean;
	/**
	 * Model ids or globs (`*`, `?`). Empty list is fail-closed: no OpenRouter
	 * models, and the runtime key is not injected.
	 */
	allowedModels: string[];
}

export interface CatalogModel {
	id: string;
	name: string;
	api?: string;
	baseUrl?: string;
	reasoning: boolean;
	thinkingLevelMap?: Record<string, string | null>;
	input: Array<"text" | "image">;
	cost: {
		input: number;
		output: number;
		cacheRead: number;
		cacheWrite: number;
		[key: string]: unknown;
	};
	contextWindow: number;
	maxTokens: number;
	headers?: Record<string, string>;
	compat?: unknown;
	samplingParams?: Record<string, unknown>;
}

export type ProviderModelConfig = {
	id: string;
	name: string;
	api?: string;
	baseUrl?: string;
	reasoning: boolean;
	thinkingLevelMap?: CatalogModel["thinkingLevelMap"];
	input: CatalogModel["input"];
	cost: CatalogModel["cost"];
	contextWindow: number;
	maxTokens: number;
	headers?: Record<string, string>;
	compat?: CatalogModel["compat"];
	samplingParams?: Record<string, unknown>;
};

export const DEFAULT_CONFIG: OpenRouterGateConfig = {
	enabled: false,
	allowedModels: [...DEFAULT_ALLOWED_MODELS],
};

export function normalizeAllowedModels(value: unknown): string[] {
	if (!Array.isArray(value)) return [...DEFAULT_ALLOWED_MODELS];
	const out: string[] = [];
	const seen = new Set<string>();
	for (const item of value) {
		if (typeof item !== "string") continue;
		const trimmed = item.trim();
		if (!trimmed || seen.has(trimmed)) continue;
		seen.add(trimmed);
		out.push(trimmed);
	}
	return out;
}

export function normalizeConfig(value: unknown): OpenRouterGateConfig {
	const raw = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
	return {
		enabled: typeof raw.enabled === "boolean" ? raw.enabled : DEFAULT_CONFIG.enabled,
		allowedModels: "allowedModels" in raw ? normalizeAllowedModels(raw.allowedModels) : [...DEFAULT_ALLOWED_MODELS],
	};
}

export function loadConfig(path: string): OpenRouterGateConfig {
	try {
		return normalizeConfig(JSON.parse(readFileSync(path, "utf8")));
	} catch {
		return { enabled: DEFAULT_CONFIG.enabled, allowedModels: [...DEFAULT_CONFIG.allowedModels] };
	}
}

export function saveConfig(path: string, config: OpenRouterGateConfig): void {
	const normalized = normalizeConfig(config);
	const temporaryPath = `${path}.${process.pid}.tmp`;
	writeFileSync(temporaryPath, `${JSON.stringify(normalized, null, 2)}\n`, { mode: 0o644 });
	renameSync(temporaryPath, path);
}

/** True only when the provider should be authed *and* expose a non-empty catalog. */
export function isProviderOpen(config: OpenRouterGateConfig): boolean {
	return config.enabled && config.allowedModels.length > 0;
}

export function isGlobPattern(pattern: string): boolean {
	return /[*?]/.test(pattern);
}

export function globToRegExp(pattern: string): RegExp {
	let source = "^";
	for (const char of pattern) {
		if (char === "*") source += ".*";
		else if (char === "?") source += ".";
		else if ("\\^$+()[]{}|.".includes(char)) source += `\\${char}`;
		else source += char;
	}
	source += "$";
	return new RegExp(source, "i");
}

export function matchesGlob(id: string, pattern: string): boolean {
	return globToRegExp(pattern).test(id);
}

/**
 * Ids to test against the allowlist: the raw id, an `openrouter/` strip,
 * and the base OpenRouter id inside a plus `@or:` variant.
 */
export function catalogIdsFor(id: string): string[] {
	const ids = [id];
	if (id.startsWith("openrouter/")) ids.push(id.slice("openrouter/".length));
	if (id.startsWith("@or:")) {
		const rest = id.slice(4);
		const slash = rest.indexOf("/");
		if (slash > 0) {
			const colon = rest.lastIndexOf(":", slash);
			ids.push(colon >= 0 ? rest.slice(colon + 1) : rest);
		}
	}
	return ids;
}

export function modelAllowed(id: string, patterns: readonly string[]): boolean {
	if (patterns.length === 0) return false;
	const candidates = catalogIdsFor(id);
	for (const pattern of patterns) {
		for (const candidate of candidates) {
			if (candidate === pattern || matchesGlob(candidate, pattern) || matchesGlob(id, pattern)) {
				return true;
			}
		}
	}
	return false;
}

export function filterModels<T extends { id: string }>(models: readonly T[], patterns: readonly string[]): T[] {
	if (patterns.length === 0) return [];
	return models.filter((model) => modelAllowed(model.id, patterns));
}

export function toProviderModelConfig(model: CatalogModel): ProviderModelConfig {
	const config: ProviderModelConfig = {
		id: model.id,
		name: model.name || model.id,
		reasoning: model.reasoning,
		input: model.input?.length ? model.input : ["text"],
		cost: {
			input: model.cost?.input ?? 0,
			output: model.cost?.output ?? 0,
			cacheRead: model.cost?.cacheRead ?? 0,
			cacheWrite: model.cost?.cacheWrite ?? 0,
		},
		contextWindow: model.contextWindow || 128000,
		maxTokens: model.maxTokens || 16384,
	};
	if (model.api) config.api = model.api;
	if (model.baseUrl) config.baseUrl = model.baseUrl;
	if (model.thinkingLevelMap) config.thinkingLevelMap = model.thinkingLevelMap;
	if (model.headers) config.headers = model.headers;
	if (model.compat) config.compat = model.compat;
	if (model.samplingParams) config.samplingParams = model.samplingParams;
	return config;
}

export function fallbackModel(id: string): ProviderModelConfig {
	if (id === "z-ai/glm-5.3-flash") {
		return {
			id,
			name: "Z.ai: GLM 5.3 Flash",
			api: "openai-completions",
			baseUrl: OPENROUTER_BASE_URL,
			reasoning: true,
			input: ["text", "image"],
			cost: { input: 0.075, output: 0.25, cacheRead: 0.015, cacheWrite: 0 },
			contextWindow: 1_048_576,
			maxTokens: 131_072,
			compat: { supportsDeveloperRole: false, thinkingFormat: "openrouter" },
		};
	}
	return {
		id,
		name: id,
		api: "openai-completions",
		baseUrl: OPENROUTER_BASE_URL,
		reasoning: true,
		input: ["text"],
		cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
		contextWindow: 128000,
		maxTokens: 16384,
		compat: { supportsDeveloperRole: false, thinkingFormat: "openrouter" },
	};
}

/** Filtered catalog plus stub entries for exact allowlist ids not yet synced. */
export function buildAllowedModels(
	catalog: readonly CatalogModel[],
	patterns: readonly string[],
): ProviderModelConfig[] {
	if (patterns.length === 0) return [];
	const filtered = filterModels(catalog, patterns).map(toProviderModelConfig);
	const present = new Set(filtered.map((model) => model.id));
	for (const pattern of patterns) {
		if (isGlobPattern(pattern) || present.has(pattern)) continue;
		filtered.push(fallbackModel(pattern));
		present.add(pattern);
	}
	return filtered;
}

export function describeConfig(config: OpenRouterGateConfig): string {
	const allow =
		config.allowedModels.length === 0
			? "allowlist empty (fail-closed)"
			: `allowlist: ${config.allowedModels.join(", ")}`;
	return `OpenRouter ${config.enabled ? "ON" : "OFF"}; ${allow}`;
}
