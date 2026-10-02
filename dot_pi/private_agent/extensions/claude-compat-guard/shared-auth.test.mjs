import assert from "node:assert/strict";
import test from "node:test";
import { execFileSync } from "node:child_process";
import { pathToFileURL } from "node:url";
import { join } from "node:path";
import { mkdtemp, access, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { withSharedAnthropicAuth } from "./shared-auth.mjs";

const nativeRoot = join(execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim(), "@earendil-works/pi-coding-agent/dist");
const { ModelRuntime } = await import(pathToFileURL(join(nativeRoot, "index.js")));
const { AuthStorage } = await import(pathToFileURL(join(nativeRoot, "core/auth-storage.js")));
const { lazyStream, createAssistantMessageEventStream } = await import(pathToFileURL(join(nativeRoot, "../node_modules/@earendil-works/pi-ai/dist/index.js")));
const provider = { id: "claude-compat", auth: { oauth: { isSubscription: true } }, stream() {}, streamSimple() {} };
const signal = new AbortController().signal;

test("every resolution delegates to the owner, ignoring override keys; availability never refreshes", async () => {
	const calls = [];
	let token = "sk-ant-oat-synthetic-first";
	const owner = {
		listCredentials: async (options) => { calls.push(["list", "anthropic", options.signal]); return [{ providerId: "anthropic", type: "oauth" }]; },
		getAuth: async (id, options) => { calls.push(["resolve", id, options.signal]); return { auth: { apiKey: token } }; },
	};
	const shared = withSharedAnthropicAuth(provider, owner);
	assert.deepEqual(await shared.auth.apiKey.check({ signal }), { type: "oauth", source: "Pi Anthropic OAuth" });
	assert.equal(calls.filter(c => c[0] === "resolve").length, 0);
	assert.equal((await shared.auth.apiKey.resolve({ signal, credential: { key: "paid-key-must-not-be-used" } })).auth.apiKey, token);
	token = "sk-ant-oat-synthetic-rotated";
	assert.equal((await shared.auth.apiKey.resolve({ signal })).auth.apiKey, token);
	assert.ok(calls.every(c => c[1] === "anthropic" && c[2] === signal));
	assert.equal(shared.auth.oauth.isSubscription, true);
});

test("missing/OAuth-invalid owner and paid API-key owner fail closed", async () => {
	for (const check of [undefined, { type: "api_key" }]) {
		let resolutions = 0;
		const shared = withSharedAnthropicAuth(provider, {
			listCredentials: async () => check ? [{ providerId: "anthropic", type: check.type }] : [],
			getAuth: async () => { resolutions++; return { auth: { apiKey: "paid-key" } }; },
		});
		assert.equal(await shared.auth.apiKey.check({ signal }), undefined);
		await assert.rejects(shared.auth.apiKey.resolve({ signal }), /requires Pi's Anthropic OAuth/);
		assert.equal(resolutions, 0);
	}
	const shared = withSharedAnthropicAuth(provider, {
		listCredentials: async () => [{ providerId: "anthropic", type: "oauth" }],
		getAuth: async () => ({ auth: { apiKey: "sk-ant-api-synthetic" } }),
	});
	await assert.rejects(shared.auth.apiKey.resolve({ signal }), /did not resolve an OAuth/);
});

test("separate Compat credential/login cannot become another refresh owner", async () => {
	const shared = withSharedAnthropicAuth(provider, {});
	await assert.rejects(shared.auth.apiKey.login(), /login anthropic/);
	await assert.rejects(shared.auth.oauth.login(), /login anthropic/);
	await assert.rejects(shared.auth.oauth.refresh(), /separate Claude Compat credential/);
	await assert.rejects(shared.auth.oauth.toAuth(), /separate Claude Compat credential/);
});

test("native Pi resolves concurrent requests with one locked Anthropic refresh; no Compat write", async () => {
	const originalOther = { type: "api_key", key: "synthetic-other-provider" };
	const storage = AuthStorage.inMemory({
		anthropic: { type: "oauth", access: "sk-ant-oat-synthetic-expired", refresh: "synthetic-refresh", expires: 0 },
		unrelated: originalOther,
	});
	const writes = [];
	const credentials = {
		read: storage.read.bind(storage), list: storage.list.bind(storage), delete: storage.delete.bind(storage),
		modify: async (id, fn, options) => { writes.push(id); return storage.modify(id, fn, options); },
	};
	const options = { credentials, modelsPath: null, allowModelNetwork: false, refreshOnCreate: false };
	const owner = await ModelRuntime.create(options);
	let refreshes = 0;
	const original = owner.getProvider("anthropic");
	owner.registerNativeProvider({ ...original, auth: { oauth: {
		...original.auth.oauth,
		refresh: async (credential, abort) => {
			abort.throwIfAborted();
			refreshes++;
			await new Promise(resolve => setImmediate(resolve));
			return { ...credential, access: "sk-ant-oat-synthetic-current", refresh: "synthetic-rotated-refresh", expires: Date.now() + 3600000 };
		},
	} } });
	const dispatched = [];
	const send = (model, context, options) => {
		dispatched.push({ model, context, options });
		const stream = createAssistantMessageEventStream();
		const message = { role: "assistant", content: [{ type: "text", text: "scripted-owner-ok" }],
			api: model.api, provider: model.provider, model: model.id, timestamp: Date.now(), stopReason: "stop",
			usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, totalTokens: 2,
				cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } } };
		stream.push({ type: "start", partial: { ...message, stopReason: "pending" } });
		stream.push({ type: "done", reason: "stop", message });
		stream.end(message);
		return stream;
	};
	const model = { id: "claude-test", name: "Scripted", provider: "claude-compat", api: "claude-compat-messages",
		baseUrl: "https://api.anthropic.com", input: ["text"], reasoning: false, contextWindow: 32000, maxTokens: 2000,
		cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } };
	const gateway = await ModelRuntime.create(options);
	gateway.registerNativeProvider(withSharedAnthropicAuth({
		...provider, name: "Scripted Compat", getModels: () => [model], getAllModels: () => [model],
		stream: send, streamSimple: send,
	}, owner, lazyStream));
	assert.equal((await gateway.checkAuth("claude-compat")).type, "oauth");
	assert.equal(refreshes, 0, "availability must not refresh expired tokens");
	await gateway.refresh({ allowNetwork: false });
	assert.equal(gateway.isUsingOAuth("claude-compat"), true);
	assert.equal(gateway.isUsingSubscription("claude-compat"), true);
	const results = await Promise.all(Array.from({ length: 8 }, () => gateway.getAuth("claude-compat", { signal })));
	assert.ok(results.every(r => r.auth.apiKey === "sk-ant-oat-synthetic-current"));
	assert.equal(refreshes, 1);
	for (const method of ["stream", "streamSimple"]) {
		const result = await gateway[method](model, { messages: [{ role: "system", content: "Scripted request", timestamp: 0 }] },
			{ apiKey: "sk-ant-oat-synthetic-wrong-override", signal }).result();
		assert.equal(result.stopReason, "stop");
		assert.equal(dispatched.at(-1).options.apiKey, "sk-ant-oat-synthetic-current");
		assert.equal(dispatched.at(-1).options.signal, signal);
	}
	assert.ok(writes.length > 0 && writes.every(id => id === "anthropic"));
	assert.equal(await storage.read("claude-compat"), undefined);
	assert.deepEqual(await storage.read("unrelated"), originalOther);
	await storage.delete("anthropic");
	assert.equal(await gateway.checkAuth("claude-compat"), undefined);
	await assert.rejects(gateway.getAuth("claude-compat"), /requires Pi's Anthropic OAuth/);
});

test("OAuth metadata gate never evaluates a stored API-key command", async () => {
	const root = await mkdtemp(join(tmpdir(), "compat-auth-command-"));
	const marker = join(root, "must-not-exist");
	try {
		const owner = await ModelRuntime.create({
			credentials: AuthStorage.inMemory({ anthropic: { type: "api_key", key: "!touch " + marker } }),
			modelsPath: null, allowModelNetwork: false, refreshOnCreate: false,
		});
		const shared = withSharedAnthropicAuth(provider, owner, lazyStream);
		assert.equal(await shared.auth.apiKey.check({ signal }), undefined);
		await assert.rejects(shared.auth.apiKey.resolve({ signal }), /requires Pi's Anthropic OAuth/);
		await assert.rejects(access(marker), error => error.code === "ENOENT");
	} finally { await rm(root, { recursive: true, force: true }); }
});
