import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { callCodexSearch } from "./codex.ts";

test("Codex search sends configured effort and preserves unset backend defaults", async (t) => {
  const home = mkdtempSync(join(tmpdir(), "web-search-codex-"));
  const previousHome = process.env.HOME;
  process.env.HOME = home;
  const agent = join(home, ".pi", "agent");
  mkdirSync(agent, { recursive: true });
  writeFileSync(join(agent, "auth.json"), JSON.stringify({
    "openai-codex": {
      type: "oauth",
      access: "dummy-test-token",
      accountId: "dummy-test-account",
      expires: Date.now() + 3_600_000,
    },
  }), { mode: 0o600 });

  try {
    for (const reasoningEffort of ["low", undefined] as const) {
      await t.test(reasoningEffort ?? "unset", async (t) => {
        const controller = new AbortController();
        let calls = 0;
        t.mock.method(globalThis, "fetch", async (url, init: RequestInit) => {
          calls++;
          assert.equal(url, "https://chatgpt.com/backend-api/codex/responses");
          assert.equal(init.signal, controller.signal);
          const body = JSON.parse(init.body as string);
          assert.equal(body.model, "gpt-6.1-sol");
          assert.equal(body.instructions, "Keep citations.");
          assert.equal(body.input[0].content[0].text, "Find Pi docs");
          assert.equal(body.tools[0].type, "web_search");
          assert.equal(body.tool_choice, "required");
          if (reasoningEffort) assert.deepEqual(body.reasoning, { effort: "low" });
          else assert.equal(Object.hasOwn(body, "reasoning"), false);
          return new Response(`event: response.completed\ndata: ${JSON.stringify({
            response: {
              model: "gpt-6.1-sol",
              usage: { input_tokens: 10, output_tokens: 20, total_tokens: 30 },
              output: [{
                type: "message",
                role: "assistant",
                content: [{
                  type: "output_text",
                  text: "Pi documentation is available.",
                  annotations: [{ type: "url_citation", url: "https://example.com/pi", title: "Pi docs" }],
                }],
              }],
            },
          })}\n\n`, { headers: { "content-type": "text/event-stream" } });
        });

        const result = await callCodexSearch({
          query: "Find Pi docs",
          model: "gpt-6.1-sol",
          reasoningEffort,
          systemPrompt: "Keep citations.",
          signal: controller.signal,
        });
        assert.equal(calls, 1);
        assert.match(result.text, /Pi documentation is available/);
        assert.match(result.text, /https:\/\/example.com\/pi/);
        assert.equal(result.details.model, "gpt-6.1-sol");
        assert.equal(result.details.usage?.total_tokens, 30);
      });
    }
  } finally {
    if (previousHome === undefined) delete process.env.HOME;
    else process.env.HOME = previousHome;
    rmSync(home, { recursive: true, force: true });
  }
});
