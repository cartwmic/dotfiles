import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

const DEFAULT_BASE_URL = "https://chatgpt.com/backend-api";
const JWT_CLAIM_PATH = "https://api.openai.com/auth";
const AUTH_CACHE_TTL_MS = 60_000;
const EXPIRY_SKEW_MS = 5 * 60 * 1000;

export interface CodexAuth {
  accessToken: string;
  accountId: string;
  source: string;
}

interface AuthJson {
  "openai-codex"?: {
    type?: string;
    access?: string;
    refresh?: string;
    expires?: number;
    accountId?: string;
  };
}

interface CodexOutputItem {
  type?: string;
  role?: string;
  id?: string;
  status?: string;
  action?: {
    type?: string;
    query?: string;
    queries?: string[];
    url?: string;
  };
  content?: Array<{
    type?: string;
    text?: string;
    annotations?: Array<{
      type?: string;
      url?: string;
      title?: string;
      start_index?: number;
      end_index?: number;
    }>;
  }>;
}

export interface CodexSearchDetails {
  model: string;
  usage?: { input_tokens: number; output_tokens: number; total_tokens?: number };
  searchQueries: string[];
  sources: Array<{ title: string; url: string; age: string | null }>;
  citations: Array<{ url?: string; title?: string; citedText: string }>;
  authSource?: string;
  error?: string;
}

let cachedAuth: CodexAuth | null = null;
let cachedAuthAt = 0;

function readJson<T>(filePath: string): T | null {
  try {
    if (!fs.existsSync(filePath)) return null;
    return JSON.parse(fs.readFileSync(filePath, "utf-8")) as T;
  } catch {
    return null;
  }
}

function extractAccountIdFromToken(token: string): string | undefined {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return undefined;
    const payload = JSON.parse(Buffer.from(parts[1], "base64url").toString("utf8")) as {
      [JWT_CLAIM_PATH]?: { chatgpt_account_id?: string };
    };
    const accountId = payload[JWT_CLAIM_PATH]?.chatgpt_account_id;
    return typeof accountId === "string" && accountId.trim() ? accountId.trim() : undefined;
  } catch {
    return undefined;
  }
}

function findCodexAuth(): CodexAuth | null {
  const authJson = readJson<AuthJson>(path.join(os.homedir(), ".pi", "agent", "auth.json"));
  const cred = authJson?.["openai-codex"];
  if (cred?.type !== "oauth" || !cred.access) return null;
  if (typeof cred.expires === "number" && cred.expires <= Date.now() + EXPIRY_SKEW_MS) return null;
  const accountId =
    (typeof cred.accountId === "string" && cred.accountId.trim()) || extractAccountIdFromToken(cred.access);
  if (!accountId) return null;
  return {
    accessToken: cred.access,
    accountId,
    source: "auth.json:openai-codex",
  };
}

export function resolveCodexAuth(): CodexAuth | null {
  const now = Date.now();
  if (cachedAuth && now - cachedAuthAt < AUTH_CACHE_TTL_MS) return cachedAuth;
  cachedAuth = findCodexAuth();
  cachedAuthAt = now;
  return cachedAuth;
}

export function describeCodexAuth(): string {
  const auth = resolveCodexAuth();
  return auth ? auth.source : "MISSING (run /login openai-codex)";
}

export function resolveCodexUrl(baseUrl = DEFAULT_BASE_URL): string {
  const normalized = (baseUrl.trim() || DEFAULT_BASE_URL).replace(/\/+$/, "");
  if (normalized.endsWith("/codex/responses")) return normalized;
  if (normalized.endsWith("/codex")) return `${normalized}/responses`;
  return `${normalized}/codex/responses`;
}

export function formatCodexItems(
  items: CodexOutputItem[],
  model: string,
  authSource: string
): { text: string; details: CodexSearchDetails } {
  const searchQueries: string[] = [];
  const sources: Array<{ title: string; url: string; age: string | null }> = [];
  const seenUrls = new Set<string>();
  const citations: CodexSearchDetails["citations"] = [];
  const textParts: string[] = [];

  for (const item of items) {
    if (item.type === "web_search_call") {
      const queries = item.action?.queries?.filter((q) => q.trim()) ?? [];
      if (queries.length > 0) searchQueries.push(...queries);
      else if (item.action?.query?.trim()) searchQueries.push(item.action.query.trim());
      continue;
    }
    if (item.type !== "message" || item.role !== "assistant") continue;
    for (const part of item.content ?? []) {
      if (part.type !== "output_text") continue;
      if (part.text) textParts.push(part.text);
      for (const annotation of part.annotations ?? []) {
        if (annotation.type !== "url_citation" || !annotation.url) continue;
        citations.push({
          url: annotation.url,
          title: annotation.title,
          citedText: "",
        });
        if (!seenUrls.has(annotation.url)) {
          seenUrls.add(annotation.url);
          sources.push({
            title: annotation.title || annotation.url,
            url: annotation.url,
            age: null,
          });
        }
      }
    }
  }

  const uniqueQueries: string[] = [];
  const seenQueries = new Set<string>();
  for (const q of searchQueries) {
    const norm = q.trim();
    if (!norm || seenQueries.has(norm)) continue;
    seenQueries.add(norm);
    uniqueQueries.push(norm);
  }

  let text = textParts.join("\n\n").trim();
  if (uniqueQueries.length > 0) {
    text += `\n\n## Searches (${uniqueQueries.length})`;
    for (const q of uniqueQueries) text += `\n- ${q}`;
  }
  if (sources.length > 0) {
    text += "\n\n## Sources";
    for (const [i, src] of sources.entries()) {
      text += `\n[${i + 1}] ${src.title}\n    ${src.url}`;
    }
  }

  return {
    text: text || "(no answer returned)",
    details: {
      model,
      searchQueries: uniqueQueries,
      sources,
      citations,
      authSource,
    },
  };
}

interface SseEvent {
  type: string;
  data?: {
    item?: CodexOutputItem;
    response?: {
      id?: string;
      model?: string;
      usage?: { input_tokens?: number; output_tokens?: number; total_tokens?: number };
      output?: CodexOutputItem[];
      error?: { message?: string; code?: string };
    };
    error?: { message?: string; code?: string };
    delta?: string;
  };
}

function parseSseFrame(frame: string): SseEvent | undefined {
  const lines = frame.split(/\r?\n/);
  let type = "";
  const dataLines: string[] = [];
  for (const line of lines) {
    if (line.startsWith("event:")) type = line.slice("event:".length).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice("data:".length).trimStart());
  }
  if (dataLines.length === 0) return undefined;
  const raw = dataLines.join("\n");
  if (raw === "[DONE]") return undefined;
  try {
    return { type, data: JSON.parse(raw) };
  } catch {
    return { type };
  }
}

async function collectSseItems(
  body: ReadableStream<Uint8Array>
): Promise<{ items: CodexOutputItem[]; model?: string; usage?: CodexSearchDetails["usage"] }> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const items: CodexOutputItem[] = [];
  let model: string | undefined;
  let usage: CodexSearchDetails["usage"] | undefined;
  let failed: string | undefined;

  const consumeFrame = (frame: string): void => {
    const event = parseSseFrame(frame);
    if (!event) return;
    if (event.type === "response.failed") {
      failed = event.data?.error?.message ?? event.data?.error?.code ?? "Codex web search failed";
      return;
    }
    if (event.type === "response.output_item.done" && event.data?.item) {
      items.push(event.data.item);
      return;
    }
    if (event.type === "response.completed") {
      model = event.data?.response?.model ?? model;
      const rawUsage = event.data?.response?.usage;
      if (rawUsage) {
        usage = {
          input_tokens: rawUsage.input_tokens ?? 0,
          output_tokens: rawUsage.output_tokens ?? 0,
          total_tokens: rawUsage.total_tokens,
        };
      }
      if (items.length === 0 && event.data?.response?.output) {
        items.push(...event.data.response.output);
      }
    }
  };

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let separator = /\r?\n\r?\n/.exec(buffer);
      while (separator && separator.index !== undefined) {
        const frame = buffer.slice(0, separator.index);
        buffer = buffer.slice(separator.index + separator[0].length);
        consumeFrame(frame);
        if (failed) throw new Error(failed);
        separator = /\r?\n\r?\n/.exec(buffer);
      }
    }
  } finally {
    reader.releaseLock();
  }

  buffer += decoder.decode();
  if (buffer.trim()) consumeFrame(buffer);
  if (failed) throw new Error(failed);
  return { items, model, usage };
}

export async function callCodexSearch(options: {
  query: string;
  model: string;
  systemPrompt?: string;
  signal?: AbortSignal;
}): Promise<{ text: string; details: CodexSearchDetails }> {
  const auth = resolveCodexAuth();
  if (!auth) {
    throw new Error(
      "openai-codex auth missing or expired. Run /login openai-codex, or /web-search provider anthropic."
    );
  }

  const headers = new Headers();
  headers.set("Authorization", `Bearer ${auth.accessToken}`);
  headers.set("chatgpt-account-id", auth.accountId);
  headers.set("originator", "pi");
  headers.set("User-Agent", "pi-web-search");
  headers.set("OpenAI-Beta", "responses=experimental");
  headers.set("accept", "text/event-stream");
  headers.set("content-type", "application/json");

  const body = {
    model: options.model,
    instructions:
      options.systemPrompt ??
      "You are a concise web search assistant. Use web search, answer the query, and preserve source citations.",
    input: [
      {
        type: "message",
        role: "user",
        content: [{ type: "input_text", text: options.query }],
      },
    ],
    tools: [
      {
        type: "web_search",
        external_web_access: true,
        search_context_size: "medium",
      },
    ],
    tool_choice: "required",
    store: false,
    stream: true,
  };

  const response = await fetch(resolveCodexUrl(), {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal: options.signal,
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Codex API error (${response.status}): ${errorText.slice(0, 500)}`);
  }
  if (!response.body) throw new Error("Codex responses response did not include a body");

  const collected = await collectSseItems(response.body);
  const formatted = formatCodexItems(collected.items, collected.model ?? options.model, auth.source);
  if (collected.usage) formatted.details.usage = collected.usage;
  return formatted;
}
