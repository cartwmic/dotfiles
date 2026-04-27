/**
 * Web Search + Web Fetch — pi extension (Anthropic-backed)
 *
 * Two tools registered against the same Anthropic auth context:
 *
 *   web_search  → Anthropic web_search_20250305 server tool. Claude does the
 *                 searches server-side and returns a synthesized answer with
 *                 cited sources. Best for "give me the answer" lookups.
 *                 Server-side max_uses defaults to 5 (raise via max_searches
 *                 up to 20). This is what Anthropic enforces hard, unlike the
 *                 fragile client-side budget in pi-codex-web-search.
 *
 *   web_fetch   → Anthropic web_fetch_20250910 server tool. Pulls a single URL
 *                 and returns the extracted page content with minimal LLM
 *                 commentary. Best for "I have a URL, give me its contents."
 *                 Use this after web_search returns a source you want to read
 *                 in full.
 *
 * Adapted from @oh-my-pi/anthropic-websearch (MIT, github.com/can1357/oh-my-pi).
 *
 * Auth resolution (first match wins):
 *   1. ANTHROPIC_SEARCH_API_KEY / ANTHROPIC_SEARCH_BASE_URL env vars
 *   2. macOS Keychain `Claude Code-credentials` (your `claude login` token)
 *   3. OAuth credentials in ~/.pi/agent/auth.json
 *   4. ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL fallback
 */

import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { Text } from "@mariozechner/pi-tui";
import { Type } from "@sinclair/typebox";

const DEFAULT_BASE_URL = "https://api.anthropic.com";
// Real Anthropic model ID (alias — resolves to current dated build). Override via ANTHROPIC_SEARCH_MODEL.
const DEFAULT_MODEL = "claude-sonnet-4-5";
const TOOL_NAME_SEARCH = "web_search";
const TOOL_NAME_FETCH = "web_fetch";

// ---------------------------------------------------------------------------
// Auth resolution
// ---------------------------------------------------------------------------

interface AuthConfig {
  apiKey: string;
  baseUrl: string;
  isOAuth: boolean;
  source: string;
}

interface AuthJson {
  anthropic?: { type: "oauth"; access: string; refresh?: string; expires: number };
}

function readJson<T>(filePath: string): T | null {
  try {
    if (!fs.existsSync(filePath)) return null;
    return JSON.parse(fs.readFileSync(filePath, "utf-8")) as T;
  } catch {
    return null;
  }
}

function isOAuthToken(apiKey: string): boolean {
  return apiKey.includes("sk-ant-oat");
}

interface ClaudeCodeKeychainCreds {
  claudeAiOauth?: {
    accessToken?: string;
    refreshToken?: string;
    expiresAt?: number;
    scopes?: string[];
  };
}

function readClaudeCodeKeychainCreds(): { accessToken: string; expiresAt?: number } | null {
  if (process.platform !== "darwin") return null;
  try {
    const raw = execFileSync(
      "security",
      ["find-generic-password", "-s", "Claude Code-credentials", "-a", os.userInfo().username, "-w"],
      { encoding: "utf-8", stdio: ["ignore", "pipe", "ignore"], timeout: 2000 }
    ).trim();
    if (!raw) return null;
    const parsed = JSON.parse(raw) as ClaudeCodeKeychainCreds;
    const oauth = parsed.claudeAiOauth;
    if (!oauth?.accessToken) return null;
    return { accessToken: oauth.accessToken, expiresAt: oauth.expiresAt };
  } catch {
    return null;
  }
}

function findAuthConfig(): AuthConfig | null {
  const piAgentDir = path.join(os.homedir(), ".pi", "agent");

  // 1. Explicit env override
  const envKey = process.env.ANTHROPIC_SEARCH_API_KEY;
  const envBase = process.env.ANTHROPIC_SEARCH_BASE_URL;
  if (envKey) {
    return {
      apiKey: envKey,
      baseUrl: envBase ?? DEFAULT_BASE_URL,
      isOAuth: isOAuthToken(envKey),
      source: "env:ANTHROPIC_SEARCH_API_KEY",
    };
  }

  // 2. macOS Keychain — Claude Code OAuth from `claude login`.
  const kc = readClaudeCodeKeychainCreds();
  if (kc && (!kc.expiresAt || kc.expiresAt > Date.now() + 5 * 60 * 1000)) {
    return {
      apiKey: kc.accessToken,
      baseUrl: DEFAULT_BASE_URL,
      isOAuth: true,
      source: "keychain:Claude Code-credentials",
    };
  }

  // 3. OAuth in auth.json (pi-managed Anthropic OAuth)
  const authJson = readJson<AuthJson>(path.join(piAgentDir, "auth.json"));
  if (
    authJson?.anthropic?.type === "oauth" &&
    authJson.anthropic.access &&
    authJson.anthropic.expires > Date.now() + 5 * 60 * 1000
  ) {
    return {
      apiKey: authJson.anthropic.access,
      baseUrl: DEFAULT_BASE_URL,
      isOAuth: true,
      source: "auth.json:oauth",
    };
  }

  // 4. Generic env fallback
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (apiKey) {
    return {
      apiKey,
      baseUrl: process.env.ANTHROPIC_BASE_URL ?? DEFAULT_BASE_URL,
      isOAuth: isOAuthToken(apiKey),
      source: "env:ANTHROPIC_API_KEY",
    };
  }

  return null;
}

// ---------------------------------------------------------------------------
// Anthropic API call (shared between search + fetch)
// ---------------------------------------------------------------------------

interface WebSearchResult {
  type: "web_search_result";
  title: string;
  url: string;
  encrypted_content: string;
  page_age: string | null;
}

interface Citation {
  type: "web_search_result_location" | "char_location";
  url?: string;
  title?: string;
  cited_text: string;
  encrypted_index?: string;
}

interface WebFetchResultDocumentSource {
  type: "text" | "base64";
  media_type?: string;
  data: string;
}

interface WebFetchResultDocument {
  type: "document" | "text";
  title?: string;
  source: WebFetchResultDocumentSource;
}

interface WebFetchResult {
  type: "web_fetch_result";
  url: string;
  content?: WebFetchResultDocument;
  retrieved_at?: string;
}

interface ContentBlock {
  type: string;
  text?: string;
  citations?: Citation[];
  name?: string;
  input?: { query?: string; url?: string };
  content?: WebSearchResult[] | WebFetchResult | unknown;
}

interface ApiResponse {
  id: string;
  model: string;
  content: ContentBlock[];
  usage: {
    input_tokens: number;
    output_tokens: number;
    cache_read_input_tokens?: number;
    cache_creation_input_tokens?: number;
    server_tool_use?: { web_search_requests?: number; web_fetch_requests?: number };
  };
  stop_reason?: string;
}

function buildHeaders(auth: AuthConfig): Record<string, string> {
  const betas = ["web-search-2025-03-05", "web-fetch-2025-09-10"];
  if (auth.isOAuth) {
    betas.push("oauth-2025-04-20", "claude-code-20250219", "prompt-caching-2024-07-31");
    return {
      "anthropic-version": "2023-06-01",
      authorization: `Bearer ${auth.apiKey}`,
      accept: "application/json",
      "content-type": "application/json",
      "anthropic-dangerous-direct-browser-access": "true",
      "anthropic-beta": betas.join(","),
      "user-agent": "claude-cli/2.0.46 (external, cli)",
      "x-app": "cli",
      "x-stainless-arch": "x64",
      "x-stainless-lang": "js",
      "x-stainless-os": "Linux",
      "x-stainless-package-version": "0.60.0",
      "x-stainless-retry-count": "1",
      "x-stainless-runtime": "node",
      "x-stainless-runtime-version": "v24.3.0",
    };
  }
  return {
    "anthropic-version": "2023-06-01",
    "x-api-key": auth.apiKey,
    accept: "application/json",
    "content-type": "application/json",
    "anthropic-beta": betas.join(","),
  };
}

function buildUrl(auth: AuthConfig): string {
  const base = `${auth.baseUrl.replace(/\/$/, "")}/v1/messages`;
  return auth.isOAuth ? `${base}?beta=true` : base;
}

async function callAnthropic(
  auth: AuthConfig,
  body: Record<string, unknown>,
  signal?: AbortSignal
): Promise<ApiResponse> {
  // OAuth requires Claude Code identity in the system blocks.
  if (auth.isOAuth) {
    const existingSystem = (body.system as Array<Record<string, unknown>> | undefined) ?? [];
    body.system = [
      {
        type: "text",
        text: "You are Claude Code, Anthropic's official CLI for Claude.",
        cache_control: { type: "ephemeral" },
      },
      ...existingSystem,
    ];
  }

  const response = await fetch(buildUrl(auth), {
    method: "POST",
    headers: buildHeaders(auth),
    body: JSON.stringify(body),
    signal,
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Anthropic API error (${response.status}): ${errorText}`);
  }

  return (await response.json()) as ApiResponse;
}

// ---------------------------------------------------------------------------
// web_search formatter
// ---------------------------------------------------------------------------

interface SearchDetails {
  model: string;
  usage: ApiResponse["usage"];
  searchQueries: string[];
  sources: Array<{ title: string; url: string; age: string | null }>;
  citations: Array<{ url?: string; title?: string; citedText: string }>;
  stopReason?: string;
  authSource?: string;
  error?: string;
}

function formatSearchResponse(
  response: ApiResponse,
  authSource: string
): { text: string; details: SearchDetails } {
  const parts: string[] = [];
  const searchQueries: string[] = [];
  const sources: Array<{ title: string; url: string; age: string | null }> = [];
  const seenUrls = new Set<string>();
  const citations: Citation[] = [];

  for (const block of response.content) {
    if (block.type === "server_tool_use" && block.name === "web_search") {
      searchQueries.push(block.input?.query ?? "");
    } else if (block.type === "web_search_tool_result" && Array.isArray(block.content)) {
      for (const result of block.content as WebSearchResult[]) {
        if (result.type === "web_search_result" && !seenUrls.has(result.url)) {
          seenUrls.add(result.url);
          sources.push({ title: result.title, url: result.url, age: result.page_age });
        }
      }
    } else if (block.type === "text" && block.text) {
      parts.push(block.text);
      if (block.citations) citations.push(...block.citations);
    }
  }

  let text = parts.join("\n\n").trim();

  // Surface the queries Claude actually issued so the calling agent can see how
  // the question was decomposed (and avoid repeating queries on a follow-up).
  const uniqueQueries: string[] = [];
  const seenQueries = new Set<string>();
  for (const q of searchQueries) {
    const norm = q.trim();
    if (!norm || seenQueries.has(norm)) continue;
    seenQueries.add(norm);
    uniqueQueries.push(norm);
  }
  if (uniqueQueries.length > 0) {
    text += `\n\n## Searches (${uniqueQueries.length})`;
    for (const q of uniqueQueries) {
      text += `\n- ${q}`;
    }
  }

  if (sources.length > 0) {
    text += "\n\n## Sources";
    for (const [i, src] of sources.entries()) {
      const age = src.age ? ` (${src.age})` : "";
      text += `\n[${i + 1}] ${src.title}${age}\n    ${src.url}`;
    }
  }

  return {
    text: text || "(no answer returned)",
    details: {
      model: response.model,
      usage: response.usage,
      searchQueries: uniqueQueries,
      sources,
      citations: citations.map((c) => ({
        url: c.url,
        title: c.title,
        citedText: c.cited_text,
      })),
      stopReason: response.stop_reason,
      authSource,
    },
  };
}

// ---------------------------------------------------------------------------
// web_fetch formatter
// ---------------------------------------------------------------------------

interface FetchDetails {
  model: string;
  usage: ApiResponse["usage"];
  url: string;
  fetchedUrls: string[];
  retrievedAt?: string;
  contentLength: number;
  truncated: boolean;
  authSource?: string;
  error?: string;
}

function decodeFetchSource(source: WebFetchResultDocumentSource): string {
  if (source.type === "text") return source.data;
  if (source.type === "base64") {
    try {
      return Buffer.from(source.data, "base64").toString("utf-8");
    } catch {
      return "";
    }
  }
  return "";
}

function formatFetchResponse(
  requestedUrl: string,
  response: ApiResponse,
  authSource: string,
  maxBytes: number
): { text: string; details: FetchDetails } {
  const fetchedUrls: string[] = [];
  let pageContent = "";
  let pageTitle: string | undefined;
  let retrievedAt: string | undefined;
  const commentary: string[] = [];

  for (const block of response.content) {
    if (block.type === "server_tool_use" && block.name === "web_fetch") {
      if (block.input?.url) fetchedUrls.push(block.input.url);
    } else if (block.type === "web_fetch_tool_result" && block.content) {
      const result = block.content as WebFetchResult;
      if (result?.type === "web_fetch_result") {
        retrievedAt = result.retrieved_at;
        if (result.content) {
          pageTitle = result.content.title;
          pageContent = decodeFetchSource(result.content.source);
        }
      }
    } else if (block.type === "text" && block.text) {
      commentary.push(block.text);
    }
  }

  // Truncate if too large (preserve head — that's where titles/intros live).
  let truncated = false;
  if (pageContent.length > maxBytes) {
    truncated = true;
    pageContent =
      pageContent.slice(0, maxBytes) +
      `\n\n[... truncated ${pageContent.length - maxBytes} bytes ...]`;
  }

  const headerLines: string[] = [];
  headerLines.push(`# Fetched: ${requestedUrl}`);
  if (pageTitle) headerLines.push(`Title: ${pageTitle}`);
  if (fetchedUrls.length > 0 && fetchedUrls[0] !== requestedUrl) {
    headerLines.push(`Final URL: ${fetchedUrls[fetchedUrls.length - 1]}`);
  }
  if (retrievedAt) headerLines.push(`Retrieved: ${retrievedAt}`);

  let text = headerLines.join("\n");
  if (pageContent) {
    text += `\n\n---\n\n${pageContent}`;
  } else {
    text += "\n\n(empty page content — Claude declined to return raw content; commentary below)";
  }

  // If Claude wrote commentary alongside the fetch, append it (rare with our prompt).
  const commentaryText = commentary.join("\n\n").trim();
  if (commentaryText && pageContent) {
    text += `\n\n---\n\n## Claude commentary\n\n${commentaryText}`;
  } else if (commentaryText && !pageContent) {
    text += `\n\n${commentaryText}`;
  }

  return {
    text,
    details: {
      model: response.model,
      usage: response.usage,
      url: requestedUrl,
      fetchedUrls,
      retrievedAt,
      contentLength: pageContent.length,
      truncated,
      authSource,
    },
  };
}

// ---------------------------------------------------------------------------
// Tool registration
// ---------------------------------------------------------------------------

const SearchSchema = Type.Object({
  query: Type.String({
    description: "The search query or question to answer using web search",
  }),
  system_prompt: Type.Optional(
    Type.String({
      description: "Optional system prompt to guide response style/focus",
    })
  ),
  max_tokens: Type.Optional(
    Type.Integer({
      minimum: 256,
      maximum: 16384,
      description: "Maximum tokens in response (default: 4096)",
    })
  ),
  max_searches: Type.Optional(
    Type.Integer({
      minimum: 1,
      maximum: 20,
      description:
        "Hard ceiling on web_search tool calls (default: 5). Anthropic enforces server-side.",
    })
  ),
});

const FetchSchema = Type.Object({
  url: Type.String({
    description: "Absolute http(s) URL to fetch and return as extracted content",
  }),
  max_tokens: Type.Optional(
    Type.Integer({
      minimum: 1024,
      maximum: 32768,
      description: "Maximum tokens in API response (default: 8192)",
    })
  ),
  max_bytes: Type.Optional(
    Type.Integer({
      minimum: 1024,
      maximum: 1_000_000,
      description:
        "Maximum extracted page bytes to return; head-truncated past this (default: 200000)",
    })
  ),
});

type SearchParams = {
  query: string;
  system_prompt?: string;
  max_tokens?: number;
  max_searches?: number;
};

type FetchParams = {
  url: string;
  max_tokens?: number;
  max_bytes?: number;
};

function getDomain(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

export default function webSearchExtension(pi: ExtensionAPI): void {
  const auth = findAuthConfig();
  const model = process.env.ANTHROPIC_SEARCH_MODEL ?? DEFAULT_MODEL;

  if (!auth) {
    const errMsg =
      "web_search/web_fetch unconfigured. Run `claude login` (writes to macOS Keychain), " +
      "set ANTHROPIC_SEARCH_API_KEY, or run `pi login` to populate ~/.pi/agent/auth.json.";
    for (const name of [TOOL_NAME_SEARCH, TOOL_NAME_FETCH]) {
      pi.registerTool({
        name,
        label: `${name} (unconfigured)`,
        description: `Anthropic-backed ${name} — currently unavailable: no auth source found.`,
        parameters: name === TOOL_NAME_SEARCH ? SearchSchema : FetchSchema,
        async execute() {
          return {
            content: [{ type: "text" as const, text: errMsg }],
            isError: true,
            details: { error: "no auth config" },
          };
        },
      });
    }
    return;
  }

  // -------------------------------------------------------------------------
  // web_search
  // -------------------------------------------------------------------------
  pi.registerTool({
    name: TOOL_NAME_SEARCH,
    label: "Web Search",
    description:
      `Search the web via Claude (${model}, Anthropic web_search_20250305). ` +
      "Returns a synthesized natural-language answer with cited sources and the queries Claude " +
      "issued. Server-side max_uses defaults to 5; raise via max_searches up to 20. " +
      "For just-the-page-contents, use web_fetch instead. " +
      `Auth: ${auth.source}.`,
    parameters: SearchSchema,
    async execute(_toolCallId, params, signal) {
      const p = params as SearchParams;
      try {
        const tool: Record<string, unknown> = {
          type: "web_search_20250305",
          name: "web_search",
          max_uses: p.max_searches ?? 5,
        };
        const body: Record<string, unknown> = {
          model,
          max_tokens: p.max_tokens ?? 4096,
          messages: [{ role: "user", content: p.query }],
          tools: [tool],
        };
        if (p.system_prompt) {
          body.system = [
            {
              type: "text",
              text: p.system_prompt,
              ...(auth.isOAuth ? { cache_control: { type: "ephemeral" } } : {}),
            },
          ];
        }
        const response = await callAnthropic(auth, body, signal);
        const { text, details } = formatSearchResponse(response, auth.source);
        return {
          content: [{ type: "text" as const, text }],
          details,
        };
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        return {
          content: [{ type: "text" as const, text: `web_search failed: ${message}` }],
          isError: true,
          details: { error: message, authSource: auth.source },
        };
      }
    },
    renderResult(result, options, theme) {
      const details = (result.details ?? {}) as Partial<SearchDetails>;
      const expanded = options.expanded;
      if (details.error) {
        return new Text(theme.fg("error", `✗ web_search: ${details.error}`), 0, 0);
      }
      const sources = details.sources ?? [];
      const queries = details.searchQueries ?? [];
      const wsReqs =
        details.usage?.server_tool_use?.web_search_requests ?? queries.length;
      const icon = sources.length > 0 ? theme.fg("success", "●") : theme.fg("warning", "●");
      const meta = theme.fg(
        "dim",
        `(${details.model ?? model}) · ${sources.length} source${sources.length === 1 ? "" : "s"}` +
          ` · ${wsReqs} search${wsReqs === 1 ? "" : "es"}`
      );
      const answer = result.content[0]?.type === "text" ? result.content[0].text : "";
      let text = `${icon} ${theme.fg("toolTitle", "Web Search")} ${meta}`;
      if (!expanded) {
        const previewLines = answer
          .split("\n")
          .filter((l) => l.trim())
          .slice(0, 3)
          .map((l) => truncate(l.trim(), 100));
        for (const line of previewLines) {
          text += `\n  ${theme.fg("dim", "│")}  ${theme.fg("dim", line)}`;
        }
        const total = answer.split("\n").filter((l) => l.trim()).length;
        if (total > 3) {
          text += `\n  ${theme.fg("dim", "│")}  ${theme.fg("muted", `… ${total - 3} more lines`)}`;
        }
        text += `\n  ${theme.fg("dim", "└─")} ${theme.fg("dim", "Ctrl+O to expand")}`;
      } else {
        for (const line of answer.split("\n")) {
          text += `\n  ${theme.fg("dim", "│")}  ${line}`;
        }
        if (sources.length > 0) {
          text += `\n  ${theme.fg("dim", "│")}`;
          text += `\n  ${theme.fg("dim", "└─")} ${theme.fg("accent", "Sources")}`;
          for (const [i, src] of sources.entries()) {
            const last = i === sources.length - 1;
            const branch = last ? "└─" : "├─";
            const cont = last ? "  " : "│ ";
            const age = src.age ? theme.fg("muted", ` · ${src.age}`) : "";
            text += `\n     ${theme.fg("dim", branch)} ${theme.fg("accent", truncate(src.title, 60))} ${theme.fg("dim", `(${getDomain(src.url)})`)}${age}`;
            text += `\n     ${theme.fg("dim", `${cont} ↳ `)}${theme.fg("link", src.url)}`;
          }
        }
      }
      return new Text(text, 0, 0);
    },
  });

  // -------------------------------------------------------------------------
  // web_fetch
  // -------------------------------------------------------------------------
  pi.registerTool({
    name: TOOL_NAME_FETCH,
    label: "Web Fetch",
    description:
      `Fetch a single URL via Claude (${model}, Anthropic web_fetch_20250910) and return the ` +
      "extracted page content. Use this when you have a specific URL (often from web_search) and " +
      "want to read the full page rather than a synthesized summary. Returns the page as markdown " +
      "with title and final-URL metadata. Truncates past max_bytes (default 200000). " +
      `Auth: ${auth.source}.`,
    parameters: FetchSchema,
    async execute(_toolCallId, params, signal) {
      const p = params as FetchParams;
      const maxBytes = p.max_bytes ?? 200_000;
      try {
        const tool = { type: "web_fetch_20250910", name: "web_fetch", max_uses: 1 };
        // System prompt constrains Claude to fetch-and-return rather than analyze.
        const body: Record<string, unknown> = {
          model,
          max_tokens: p.max_tokens ?? 8192,
          messages: [
            {
              role: "user",
              content:
                `Fetch the page at ${p.url} using the web_fetch tool and return its raw content. ` +
                `Do not summarize, analyze, or comment on the content. ` +
                `If the fetch fails, report the error briefly.`,
            },
          ],
          tools: [tool],
          system: [
            {
              type: "text",
              text:
                "You are a URL-fetching tool. When asked to fetch a URL, call web_fetch on it " +
                "exactly once and then respond with a single empty line. Do not summarize or " +
                "analyze the page contents — the calling agent will read the fetched content " +
                "directly from the tool result block.",
              ...(auth.isOAuth ? { cache_control: { type: "ephemeral" } } : {}),
            },
          ],
        };
        const response = await callAnthropic(auth, body, signal);
        const { text, details } = formatFetchResponse(p.url, response, auth.source, maxBytes);
        return {
          content: [{ type: "text" as const, text }],
          details,
        };
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        return {
          content: [{ type: "text" as const, text: `web_fetch failed: ${message}` }],
          isError: true,
          details: { error: message, authSource: auth.source, url: p.url },
        };
      }
    },
    renderResult(result, options, theme) {
      const details = (result.details ?? {}) as Partial<FetchDetails>;
      const expanded = options.expanded;
      if (details.error) {
        return new Text(theme.fg("error", `✗ web_fetch: ${details.error}`), 0, 0);
      }
      const len = details.contentLength ?? 0;
      const trunc = details.truncated ? " (truncated)" : "";
      const icon = len > 0 ? theme.fg("success", "●") : theme.fg("warning", "●");
      const url = details.url ?? "(no url)";
      const meta = theme.fg(
        "dim",
        `(${details.model ?? model}) · ${len.toLocaleString()} bytes${trunc}`
      );
      const body = result.content[0]?.type === "text" ? result.content[0].text : "";
      let text = `${icon} ${theme.fg("toolTitle", "Web Fetch")} ${theme.fg("link", url)} ${meta}`;
      if (!expanded) {
        const previewLines = body
          .split("\n")
          .filter((l) => l.trim())
          .slice(0, 3)
          .map((l) => truncate(l.trim(), 100));
        for (const line of previewLines) {
          text += `\n  ${theme.fg("dim", "│")}  ${theme.fg("dim", line)}`;
        }
        text += `\n  ${theme.fg("dim", "└─")} ${theme.fg("dim", "Ctrl+O to expand")}`;
      } else {
        for (const line of body.split("\n")) {
          text += `\n  ${theme.fg("dim", "│")}  ${line}`;
        }
      }
      return new Text(text, 0, 0);
    },
  });
}
