import assert from "node:assert/strict";
import test from "node:test";
import { execFileSync } from "node:child_process";
import { pathToFileURL } from "node:url";
import { join } from "node:path";
import { withHubKey } from "./load.mjs";

const nativeRoot = join(execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim(), "@earendil-works/pi-coding-agent/dist");
const { ModelRuntime } = await import(pathToFileURL(join(nativeRoot, "index.js")));
const { AuthStorage } = await import(pathToFileURL(join(nativeRoot, "core/auth-storage.js")));
const { lazyStream, createAssistantMessageEventStream } = await import(pathToFileURL(join(nativeRoot, "../node_modules/@earendil-works/pi-ai/dist/index.js")));

const HUB = "cpa_0123456789abcdef0123456789abcdef";
const model = { id: "claude-test", name: "Scripted", provider: "claude-compat", api: "claude-compat-messages",
	baseUrl: "https://api.anthropic.com", input: ["text"], reasoning: false, contextWindow: 32000, maxTokens: 2000,
	cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } };

function scripted(dispatched) {
	return (m, context, options) => {
		dispatched.push(options);
		const stream = createAssistantMessageEventStream();
		const message = { role: "assistant", content: [{ type: "text", text: "ok" }], api: m.api, provider: m.provider,
			model: m.id, timestamp: Date.now(), stopReason: "stop", usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0,
				totalTokens: 2, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } } };
		stream.push({ type: "start", partial: { ...message, stopReason: "pending" } });
		stream.push({ type: "done", reason: "stop", message });
		stream.end(message);
		return stream;
	};
}

test("through the real ModelRuntime, only the 1Password hub key is dispatched, whatever the caller or storage supplies", async () => {
	const storage = AuthStorage.inMemory({ "claude-compat": { type: "api_key", key: "cpa_storedstoredstoredstored" } });
	const runtime = await ModelRuntime.create({ credentials: storage, modelsPath: null, allowModelNetwork: false, refreshOnCreate: false });
	const dispatched = [];
	const send = scripted(dispatched);
	runtime.registerNativeProvider(withHubKey({ id: "claude-compat", name: "Scripted Compat", auth: {},
		getModels: () => [model], getAllModels: () => [model], stream: send, streamSimple: send }, async () => HUB, lazyStream));
	assert.equal((await runtime.checkAuth("claude-compat")).type, "api_key");
	assert.equal((await runtime.getAuth("claude-compat")).auth.apiKey, HUB);
	const signal = new AbortController().signal;
	for (const method of ["stream", "streamSimple"]) {
		for (const override of [undefined, "cpa_otherotherotherotherother", "sk-ant-oat01-override"]) {
			const result = await runtime[method](model, { messages: [{ role: "user", content: "hi", timestamp: 0 }] },
				{ apiKey: override, signal }).result();
			assert.equal(result.stopReason, "stop", `${method} ${override}: ${result.errorMessage}`);
			assert.equal(dispatched.at(-1).apiKey, HUB, `${method} ${override}`);
			assert.equal(dispatched.at(-1).signal, signal);
		}
	}
});

test("a bad 1Password value fails the request before dispatch", async () => {
	const dispatched = [];
	const send = scripted(dispatched);
	const provider = withHubKey({ id: "claude-compat", stream: send, streamSimple: send }, async () => "sk-ant-oat01-wrong", lazyStream);
	for (const method of ["stream", "streamSimple"]) {
		const result = await provider[method](model, { messages: [] }, { apiKey: HUB }).result();
		assert.equal(result.stopReason, "error");
		assert.match(result.errorMessage, /not a cpa_ hub client key/);
	}
	assert.equal(dispatched.length, 0);
});
