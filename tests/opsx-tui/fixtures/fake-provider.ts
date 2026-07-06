export default function (pi: any) {
  const baseUrl = process.env.OPSX_TUI_FAKE_BASE_URL ?? "http://127.0.0.1:9/v1";

  pi.registerProvider("opsx-tui-fake", {
    name: "opsx TUI Fake",
    baseUrl,
    apiKey: "opsx-tui-fake-key",
    api: "openai-completions",
    models: [
      {
        id: "smoke",
        name: "opsx TUI Smoke",
        reasoning: false,
        input: ["text"],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        contextWindow: 32000,
        maxTokens: 1024,
        compat: {
          supportsDeveloperRole: false,
          supportsReasoningEffort: false,
          maxTokensField: "max_tokens",
        },
      },
    ],
  });
}
