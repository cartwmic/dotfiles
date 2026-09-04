import { readFileSync, renameSync, writeFileSync } from "node:fs";

export const SEARCH_PROVIDERS = ["anthropic", "codex"] as const;
export type SearchProvider = (typeof SEARCH_PROVIDERS)[number];

export const DEFAULT_ANTHROPIC_MODEL = "claude-opus-5";
export const DEFAULT_CODEX_MODEL = "gpt-5.6-luna";
export const TOOL_NAME_SEARCH = "web_search";
export const TOOL_NAME_SEARCH_PRIVATE = "claude_web_search";
export const TOOL_NAME_FETCH = "web_fetch";
export const PRIVATE_SEARCH_PROVIDER = "private-anthropic";
export const SEARCH_TOOL_NAMES = [TOOL_NAME_SEARCH, TOOL_NAME_SEARCH_PRIVATE] as const;

export function searchToolNameForProvider(provider: string | undefined): string {
  return provider === PRIVATE_SEARCH_PROVIDER ? TOOL_NAME_SEARCH_PRIVATE : TOOL_NAME_SEARCH;
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
  /** Codex Responses model for the search side-call. */
  codexModel: string;
}

export interface EffectiveWebSearchConfig {
  searchProvider: SearchProvider;
  anthropicModel: string;
  codexModel: string;
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

export function normalizeConfig(value: unknown): WebSearchConfig {
  const raw = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  const anthropicModel = optionalModel(raw.anthropicModel);
  return {
    searchProvider: isSearchProvider(raw.searchProvider) ? raw.searchProvider : DEFAULT_CONFIG.searchProvider,
    ...(anthropicModel ? { anthropicModel } : {}),
    codexModel: optionalModel(raw.codexModel) ?? DEFAULT_CODEX_MODEL,
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
  return (
    `web-search provider ${provider}; anthropic ${effective.anthropicModel}; ` +
    `codex ${effective.codexModel}; fetch ${effective.searchProvider === "anthropic" ? "listed (anthropic)" : "omitted (codex)"}`
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
