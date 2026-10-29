import { readFileSync, renameSync, writeFileSync } from "node:fs";

export const SEARCH_PROVIDERS = ["anthropic", "codex"] as const;
export type SearchProvider = (typeof SEARCH_PROVIDERS)[number];

export const DEFAULT_ANTHROPIC_MODEL = "claude-opus-5";
export const DEFAULT_CODEX_MODEL = "gpt-5.6-luna";
export const CODEX_REASONING_EFFORTS = ["none", "minimal", "low", "medium", "high", "xhigh"] as const;
export type CodexReasoningEffort = (typeof CODEX_REASONING_EFFORTS)[number];
export const ANTHROPIC_THINKING_LEVELS = ["off", "minimal", "low", "medium", "high", "xhigh"] as const;
export type AnthropicThinking = (typeof ANTHROPIC_THINKING_LEVELS)[number];
// Mirrors pi's DEFAULT_THINKING_BUDGETS for minimal..high. xhigh gets double the
// high budget: the search side-call is a one-shot raw Anthropic request, so unlike
// pi's chat path there is no adaptive-thinking effort tier to delegate to.
export const ANTHROPIC_THINKING_BUDGETS: Record<Exclude<AnthropicThinking, "off">, number> = {
  minimal: 1024,
  low: 2048,
  medium: 8192,
  high: 16384,
  xhigh: 32000,
};

export function anthropicThinkingBudget(
  level: AnthropicThinking | undefined
): number | undefined {
  if (!level || level === "off") return undefined;
  return ANTHROPIC_THINKING_BUDGETS[level];
}
export const TOOL_NAME_SEARCH = "web_search";
export const TOOL_NAME_SEARCH_PRIVATE = "claude_web_search";
export const TOOL_NAME_FETCH = "web_fetch";
// NOTE: these are *model* providers (keys in ~/.pi/agent/models.json), not search
// backends. Do not confuse with SEARCH_PROVIDERS above, which selects who performs
// the search. This list answers a different question: is the current chat model
// served by an Axon Open Road gateway (litellm.boost-llm.dev or Otari)?
//
// It matters because that gateway intercepts any tool literally named `web_search`
// as a server-side tool and answers via its OpenAI-completions shim, which emits SSE
// `data:` frames with no `event:` field lines. pi's Anthropic parser dispatches on
// `event:`, so it never sees `message_delta`, never gets a stop_reason, and throws
// "Anthropic stream ended without a stop reason" — then retries forever. Aliasing the
// tool name keeps the request on the gateway's native Anthropic path.
export const WEB_SEARCH_ALIAS_PROVIDERS = ["private-anthropic", "private-glm-otari"] as const;
export const SEARCH_TOOL_NAMES = [TOOL_NAME_SEARCH, TOOL_NAME_SEARCH_PRIVATE] as const;

export function searchToolNameForProvider(modelProvider: string | undefined): string {
  return modelProvider !== undefined &&
    (WEB_SEARCH_ALIAS_PROVIDERS as readonly string[]).includes(modelProvider)
    ? TOOL_NAME_SEARCH_PRIVATE
    : TOOL_NAME_SEARCH;
}

export function nextActiveWebSearchTools(
  activeTools: string[],
  nextModelProvider: string | undefined,
  previousModelProvider: string | undefined,
  searchProvider: SearchProvider
): string[] {
  const previousName = previousModelProvider
    ? searchToolNameForProvider(previousModelProvider)
    : TOOL_NAME_SEARCH;
  const searchEnabled = activeTools.includes(previousName);
  const nextTools = activeTools.filter(
    (name) =>
      !SEARCH_TOOL_NAMES.includes(name as (typeof SEARCH_TOOL_NAMES)[number]) &&
      name !== TOOL_NAME_FETCH
  );
  if (searchEnabled) nextTools.push(searchToolNameForProvider(nextModelProvider));
  if (searchProvider === "anthropic") nextTools.push(TOOL_NAME_FETCH);
  return nextTools;
}

export interface WebSearchConfig {
  /** Backend for `web_search`; Codex omits the Anthropic-only `web_fetch` tool. */
  searchProvider: SearchProvider;
  /** Optional Claude model override. Unset → `ANTHROPIC_SEARCH_MODEL` or default. */
  anthropicModel?: string;
  /** Thinking level for the Anthropic search side-call. Unset or "off" → no thinking param. */
  anthropicThinking?: AnthropicThinking;
  /** Codex Responses model for the search side-call. */
  codexModel: string;
  /** Unset preserves the Codex backend's default reasoning effort. */
  codexReasoningEffort?: CodexReasoningEffort;
}

export interface EffectiveWebSearchConfig {
  searchProvider: SearchProvider;
  anthropicModel: string;
  anthropicThinking?: AnthropicThinking;
  codexModel: string;
  codexReasoningEffort?: CodexReasoningEffort;
  providerSource: "env" | "config";
}

export const DEFAULT_CONFIG: WebSearchConfig = {
  searchProvider: "anthropic",
  codexModel: DEFAULT_CODEX_MODEL,
};

function isSearchProvider(value: unknown): value is SearchProvider {
  return typeof value === "string" && SEARCH_PROVIDERS.includes(value as SearchProvider);
}

function optionalModel(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

function optionalThinkingLevel(value: unknown): AnthropicThinking | undefined {
  if (typeof value !== "string") return undefined;
  const level = value.trim().toLowerCase();
  return ANTHROPIC_THINKING_LEVELS.includes(level as AnthropicThinking)
    ? (level as AnthropicThinking)
    : undefined;
}

function optionalReasoningEffort(value: unknown): CodexReasoningEffort | undefined {
  if (typeof value !== "string") return undefined;
  const effort = value.trim().toLowerCase();
  return CODEX_REASONING_EFFORTS.includes(effort as CodexReasoningEffort)
    ? (effort as CodexReasoningEffort)
    : undefined;
}

export function normalizeConfig(value: unknown): WebSearchConfig {
  const raw = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  const anthropicModel = optionalModel(raw.anthropicModel);
  const anthropicThinking = optionalThinkingLevel(raw.anthropicThinking);
  const codexReasoningEffort = optionalReasoningEffort(raw.codexReasoningEffort);
  return {
    searchProvider: isSearchProvider(raw.searchProvider) ? raw.searchProvider : DEFAULT_CONFIG.searchProvider,
    ...(anthropicModel ? { anthropicModel } : {}),
    ...(anthropicThinking ? { anthropicThinking } : {}),
    codexModel: optionalModel(raw.codexModel) ?? DEFAULT_CODEX_MODEL,
    ...(codexReasoningEffort ? { codexReasoningEffort } : {}),
  };
}

export function loadConfig(path: string): WebSearchConfig {
  try {
    return normalizeConfig(JSON.parse(readFileSync(path, "utf8")));
  } catch {
    return { ...DEFAULT_CONFIG };
  }
}

export function saveConfig(path: string, config: WebSearchConfig): void {
  const normalized = normalizeConfig(config);
  const temporaryPath = `${path}.${process.pid}.tmp`;
  writeFileSync(temporaryPath, `${JSON.stringify(normalized, null, 2)}\n`, { mode: 0o644 });
  renameSync(temporaryPath, path);
}

export function resolveEffectiveConfig(
  config: WebSearchConfig,
  env: NodeJS.ProcessEnv = process.env
): EffectiveWebSearchConfig {
  const envProvider = env.WEB_SEARCH_PROVIDER?.trim().toLowerCase();
  const searchProvider = isSearchProvider(envProvider) ? envProvider : config.searchProvider;
  return {
    searchProvider,
    anthropicModel:
      optionalModel(env.ANTHROPIC_SEARCH_MODEL) ?? config.anthropicModel ?? DEFAULT_ANTHROPIC_MODEL,
    codexModel: optionalModel(env.CODEX_SEARCH_MODEL) ?? config.codexModel,
    codexReasoningEffort:
      optionalReasoningEffort(env.CODEX_SEARCH_REASONING_EFFORT) ?? config.codexReasoningEffort,
    anthropicThinking:
      optionalThinkingLevel(env.ANTHROPIC_SEARCH_THINKING) ?? config.anthropicThinking,
    providerSource: isSearchProvider(envProvider) ? "env" : "config",
  };
}

export function describeConfig(
  config: WebSearchConfig,
  env: NodeJS.ProcessEnv = process.env
): string {
  const effective = resolveEffectiveConfig(config, env);
  const provider =
    effective.providerSource === "env"
      ? `${effective.searchProvider} (WEB_SEARCH_PROVIDER)`
      : effective.searchProvider;
  const thinking = effective.anthropicThinking ? ` (thinking ${effective.anthropicThinking})` : "";
  return (
    `web-search provider ${provider}; anthropic ${effective.anthropicModel}${thinking}; ` +
    `codex ${effective.codexModel} (effort ${effective.codexReasoningEffort ?? "backend default"}); ` +
    `fetch ${effective.searchProvider === "anthropic" ? "listed (anthropic)" : "omitted (codex)"}`
  );
}

export const WEB_SEARCH_COMMANDS = [
  "status",
  "config",
  "reload",
  "provider",
  "provider anthropic",
  "provider codex",
] as const;

export type WebSearchCommand =
  | { kind: "status" }
  | { kind: "reload" }
  | { kind: "config" }
  | { kind: "provider"; provider: SearchProvider }
  | { kind: "usage"; message: string };

export function parseWebSearchCommand(args: string): WebSearchCommand {
  const parts = args.trim().split(/\s+/).filter(Boolean);
  const action = (parts[0] ?? "status").toLowerCase();
  if (action === "reload") return { kind: "reload" };
  if (action === "config") return { kind: "config" };
  if (action === "status") return { kind: "status" };
  if (action === "provider") {
    const rest = parts.slice(1).join(" ").toLowerCase();
    if (isSearchProvider(rest)) return { kind: "provider", provider: rest };
    return { kind: "usage", message: "Usage: /web-search provider anthropic|codex" };
  }
  return {
    kind: "usage",
    message: "Usage: /web-search [status | config | provider anthropic|codex | reload]",
  };
}
