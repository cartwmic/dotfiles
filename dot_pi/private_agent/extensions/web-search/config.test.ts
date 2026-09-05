import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import {
  DEFAULT_ANTHROPIC_MODEL,
  DEFAULT_CODEX_MODEL,
  DEFAULT_CONFIG,
  describeConfig,
  loadConfig,
  nextActiveWebSearchTools,
  normalizeConfig,
  parseWebSearchCommand,
  resolveEffectiveConfig,
  saveConfig,
} from "./config.ts";
import { formatCodexItems, resolveCodexUrl } from "./codex.ts";

test("defaults to Anthropic search and Luna for Codex", () => {
  assert.deepEqual(normalizeConfig(undefined), DEFAULT_CONFIG);
  assert.equal(DEFAULT_CONFIG.searchProvider, "anthropic");
  assert.equal(DEFAULT_CONFIG.codexModel, DEFAULT_CODEX_MODEL);
});

test("accepts anthropic or codex and ignores unknown providers", () => {
  assert.equal(normalizeConfig({ searchProvider: "codex" }).searchProvider, "codex");
  assert.equal(normalizeConfig({ searchProvider: "openai" }).searchProvider, "anthropic");
});

test("trims models and drops empty anthropicModel", () => {
  const cfg = normalizeConfig({
    searchProvider: "codex",
    anthropicModel: " claude-opus-5 ",
    codexModel: " gpt-5.6-sol ",
  });
  assert.equal(cfg.anthropicModel, "claude-opus-5");
  assert.equal(cfg.codexModel, "gpt-5.6-sol");
  assert.equal(normalizeConfig({ anthropicModel: "   " }).anthropicModel, undefined);
  assert.equal(normalizeConfig({ codexModel: "" }).codexModel, DEFAULT_CODEX_MODEL);
});

test("invalid WEB_SEARCH_PROVIDER falls through to config", () => {
  const cfg = normalizeConfig({ searchProvider: "codex" });
  const effective = resolveEffectiveConfig(cfg, { WEB_SEARCH_PROVIDER: "openai" });
  assert.equal(effective.searchProvider, "codex");
  assert.equal(effective.providerSource, "config");
});

test("env overrides provider and models without writing config", () => {
  const cfg = normalizeConfig({ searchProvider: "anthropic", codexModel: "gpt-5.6-sol" });
  const env = {
    WEB_SEARCH_PROVIDER: "codex",
    ANTHROPIC_SEARCH_MODEL: "claude-sonnet-5",
    CODEX_SEARCH_MODEL: "gpt-5.6-luna",
  };
  const effective = resolveEffectiveConfig(cfg, env);
  assert.equal(effective.searchProvider, "codex");
  assert.equal(effective.providerSource, "env");
  assert.equal(effective.anthropicModel, "claude-sonnet-5");
  assert.equal(effective.codexModel, "gpt-5.6-luna");
  assert.equal(resolveEffectiveConfig(cfg, {}).anthropicModel, DEFAULT_ANTHROPIC_MODEL);
});

test("describeConfig names the env override", () => {
  const text = describeConfig(DEFAULT_CONFIG, { WEB_SEARCH_PROVIDER: "codex" });
  assert.match(text, /provider codex \(WEB_SEARCH_PROVIDER\)/);
  assert.match(text, /fetch omitted \(codex\)/);
});

test("active tool listing omits fetch for Codex and restores it for Anthropic", () => {
  const codexTools = nextActiveWebSearchTools(
    ["read", "web_search", "claude_web_search", "web_fetch"],
    "openrouter",
    undefined,
    "codex"
  );
  assert.deepEqual(codexTools, ["read", "web_search"]);

  const anthropicTools = nextActiveWebSearchTools(
    codexTools,
    "openrouter",
    "openrouter",
    "anthropic"
  );
  assert.deepEqual(anthropicTools, ["read", "web_search", "web_fetch"]);

  const privateTools = nextActiveWebSearchTools(
    ["read", "web_search", "web_fetch"],
    "private-anthropic",
    "openrouter",
    "codex"
  );
  assert.deepEqual(privateTools, ["read", "claude_web_search"]);

  // private-glm shares the Open Road gateway, so it needs the same alias.
  const privateGlmTools = nextActiveWebSearchTools(
    ["read", "web_search", "web_fetch"],
    "private-glm",
    "openrouter",
    "codex"
  );
  assert.deepEqual(privateGlmTools, ["read", "claude_web_search"]);

  // Switching back off the gateway restores the public name.
  const backToPublic = nextActiveWebSearchTools(
    ["read", "claude_web_search"],
    "anthropic",
    "private-glm",
    "codex"
  );
  assert.deepEqual(backToPublic, ["read", "web_search"]);
});

test("loadConfig falls back on missing or invalid files", () => {
  const dir = mkdtempSync(join(tmpdir(), "web-search-config-"));
  try {
    const missing = join(dir, "missing.json");
    assert.deepEqual(loadConfig(missing), DEFAULT_CONFIG);
    const invalid = join(dir, "invalid.json");
    writeFileSync(invalid, "{not json");
    assert.deepEqual(loadConfig(invalid), DEFAULT_CONFIG);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("saveConfig round-trips a normalized file", () => {
  const dir = mkdtempSync(join(tmpdir(), "web-search-config-"));
  try {
    const file = join(dir, "config.json");
    saveConfig(file, { searchProvider: "codex", anthropicModel: " claude-opus-5 ", codexModel: "gpt-5.6-terra" });
    const written = JSON.parse(readFileSync(file, "utf8"));
    assert.equal(written.searchProvider, "codex");
    assert.equal(written.anthropicModel, "claude-opus-5");
    assert.equal(written.codexModel, "gpt-5.6-terra");
    assert.deepEqual(loadConfig(file), {
      searchProvider: "codex",
      anthropicModel: "claude-opus-5",
      codexModel: "gpt-5.6-terra",
    });
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("resolveCodexUrl appends /codex/responses", () => {
  assert.equal(resolveCodexUrl("https://chatgpt.com/backend-api"), "https://chatgpt.com/backend-api/codex/responses");
  assert.equal(resolveCodexUrl("https://chatgpt.com/backend-api/codex"), "https://chatgpt.com/backend-api/codex/responses");
  assert.equal(
    resolveCodexUrl("https://chatgpt.com/backend-api/codex/responses/"),
    "https://chatgpt.com/backend-api/codex/responses"
  );
});

test("parseWebSearchCommand defaults to status and rejects unknown actions", () => {
  assert.deepEqual(parseWebSearchCommand(""), { kind: "status" });
  assert.deepEqual(parseWebSearchCommand("STATUS"), { kind: "status" });
  assert.deepEqual(parseWebSearchCommand("reload"), { kind: "reload" });
  assert.deepEqual(parseWebSearchCommand("config"), { kind: "config" });
  assert.deepEqual(parseWebSearchCommand("provider codex"), {
    kind: "provider",
    provider: "codex",
  });
  assert.equal(parseWebSearchCommand("provider openai").kind, "usage");
  assert.equal(parseWebSearchCommand("on").kind, "usage");
});

test("formatCodexItems joins answer, queries, and citation sources", () => {
  const { text, details } = formatCodexItems(
    [
      {
        type: "web_search_call",
        action: { type: "search", queries: ["pi coding agent web search"] },
      },
      {
        type: "message",
        role: "assistant",
        content: [
          {
            type: "output_text",
            text: "Pi can search via an extension.",
            annotations: [
              {
                type: "url_citation",
                url: "https://example.com/docs",
                title: "Pi docs",
              },
            ],
          },
        ],
      },
    ],
    "gpt-5.6-luna",
    "auth.json:openai-codex"
  );
  assert.match(text, /Pi can search via an extension/);
  assert.match(text, /## Searches \(1\)/);
  assert.match(text, /pi coding agent web search/);
  assert.match(text, /\[1\] Pi docs/);
  assert.equal(details.model, "gpt-5.6-luna");
  assert.equal(details.sources[0]?.url, "https://example.com/docs");
  assert.equal(details.authSource, "auth.json:openai-codex");
});
