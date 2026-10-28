import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { guardProvider, rewriteContext, rewriteDocs } from "./guard.mjs";
import { HUB_KEY_REF, HUB_ORIGIN, loadCompat } from "./load.mjs";

const docs = "<docs>\nPi documentation (read only when the user asks about pi itself, its SDK, extensions, themes, skills, or TUI):\n- Main documentation: /real/pi/README.md\n- When asked about: models (docs/models.md), pi packages (docs/packages.md), MCP servers (docs/mcp.md)\n- Run pi and read pi docs\n</docs>";
const fixed = docs.replace("about pi itself", "about Pi itself").replace("pi packages (docs/packages.md)", "Pi packages (docs/packages.md)");
const model = { provider: "claude-compat", api: "claude-compat-messages" };
function freeze(value) {
	if (value && typeof value === "object") { Object.values(value).forEach(freeze); Object.freeze(value); }
	return value;
}
function fixture() {
	return freeze({ messages: [
		{ role: "system", content: "", sections: { docs, project_context: docs }, toolsAdded: [{ name: "read" }], timestamp: 0 },
		{ role: "user", content: docs, timestamp: 1 },
		{ role: "assistant", content: [{ type: "text", text: docs }], timestamp: 2 },
		{ role: "toolResult", content: [{ type: "text", text: docs }], timestamp: 3 },
		{ role: "system", content: "", sections: { docs }, timestamp: 4 },
		{ role: "system", content: docs, replace: true, timestamp: 5 },
		{ role: "system", content: [{ type: "text", text: docs, textSignature: "opaque" }], timestamp: 6 },
		{ role: "system", content: "", sections: { docs: null }, timestamp: 7 },
	] });
}
test("only copied system docs change; historical updates, flattened prompts and text blocks are covered", () => {
	const original = fixture();
	const before = JSON.stringify(original);
	const result = rewriteContext(model, original);
	assert.notEqual(result, original);
	assert.equal(result.messages[0].sections.docs, fixed);
	assert.equal(result.messages[0].sections.project_context, docs);
	assert.equal(result.messages[0].toolsAdded, original.messages[0].toolsAdded);
	for (const i of [1, 2, 3, 7]) assert.equal(result.messages[i], original.messages[i]);
	assert.equal(result.messages[4].sections.docs, fixed);
	assert.equal(result.messages[5].content, fixed);
	assert.equal(result.messages[6].content[0].text, fixed);
	assert.equal(result.messages[6].content[0].textSignature, "opaque");
	assert.equal(JSON.stringify(original), before);
	assert.equal(rewriteContext(model, result), result);
});
test("both actual-model predicates are required, regardless of session model", () => {
	const context = fixture();
	for (const candidate of [
		{ ...model, provider: "anthropic" },
		{ ...model, api: "anthropic-messages" },
		{ provider: "claude-bridge", api: "claude-bridge" },
	]) assert.equal(rewriteContext(candidate, context), context);
});
test("custom or ambiguous docs are not rewritten; exact paths and commands stay intact", () => {
	assert.equal(rewriteDocs("about pi itself, its SDK; pi packages (docs/packages.md)"), "about pi itself, its SDK; pi packages (docs/packages.md)");
	assert.equal(rewriteDocs(docs + "\n" + docs), docs + "\n" + docs);
	assert.equal(rewriteDocs(fixed), fixed);
	assert.equal(rewriteDocs(null), null);
	assert.equal(rewriteDocs(docs), fixed);
	const differences = [...docs].flatMap((char, i) => char !== fixed[i] ? [[char, fixed[i]]] : []);
	assert.deepEqual(differences, [["p", "P"], ["p", "P"]]);
});
test("both stream entrypoints preserve provider metadata, options, receiver, results and actual-model scope", () => {
	const calls = [], sentinel = {}, options = freeze({ maxTokens: 123, signal: new AbortController().signal });
	const context = fixture();
	const provider = { id: "claude-compat", auth: { oauth: {} }, getModels: () => [],
		stream(m, c, o) { calls.push([this, m, c, o]); return sentinel; },
		streamSimple(m, c, o) { calls.push([this, m, c, o]); return sentinel; },
	};
	const guarded = guardProvider(provider);
	assert.equal(guarded.auth, provider.auth);
	assert.equal(guarded.getModels, provider.getModels);
	for (const method of ["stream", "streamSimple"]) {
		assert.equal(guarded[method](model, context, options), sentinel);
		assert.deepEqual(calls.at(-1), [provider, model, rewriteContext(model, context), options]);
		const foreign = { ...model, provider: "anthropic" };
		guarded[method](foreign, context, options);
		assert.equal(calls.at(-1)[2], context);
	}
});
test("factory registers the guarded raw provider exactly once before any session context exists", async () => {
	const registrations = [], commands = [];
	const pi = { registerProvider: p => registrations.push(p), registerCommand: (...args) => commands.push(args) };
	const provider = { id: "claude-compat", auth: { oauth: { isSubscription: true } }, stream() {}, streamSimple() {} };
	await loadCompat(pi, api => { api.registerProvider(provider); api.registerCommand("upstream-status", {}); }, {}, undefined, { mode: "direct" });
	assert.equal(registrations.length, 1);
	assert.notEqual(registrations[0].stream, provider.stream);
	assert.notEqual(registrations[0].streamSimple, provider.streamSimple);
	assert.equal(registrations[0].auth.oauth.isSubscription, true);
	assert.equal(commands[0][0], "upstream-status");
	await assert.rejects(loadCompat(pi, api => api.registerProvider({ id: "other" }), {}, undefined, { mode: "direct" }), /Expected the pinned/);
});
const ownerWith = (credentials, apiKey) => ({
	listCredentials: async () => credentials,
	getAuth: async (id) => id === "anthropic" ? { auth: { apiKey } } : undefined,
});
test("direct mode keeps the shared Anthropic OAuth wrapper and passes only the mode", async () => {
	const registrations = [], seen = [];
	const provider = { id: "claude-compat", auth: { oauth: { isSubscription: true } }, stream() {}, streamSimple() {} };
	await loadCompat({ registerProvider: p => registrations.push(p) },
		async (api, options) => { seen.push(options); api.registerProvider(provider); }, ownerWith([], undefined), undefined, { mode: "direct" });
	assert.deepEqual(seen, [{ mode: "direct" }]);
	assert.equal(registrations.length, 1);
	assert.match(registrations[0].auth.oauth.name, /shared Pi Anthropic OAuth/);
});
test("proxy mode passes the hub origin and an owner-backed direct fallback, with the hub key from 1Password", async () => {
	const registrations = [], seen = [], keyReads = [];
	const auth = { apiKey: { name: "hub key", resolve() { assert.fail("the fork's own key lookup must not be used"); } } };
	const provider = { id: "claude-compat", auth, stream() {}, streamSimple() {} };
	const upstream = async (api, options) => { seen.push(options); api.registerProvider(provider); };
	const oauth = [{ providerId: "anthropic", type: "oauth" }];
	const hubKey = async (signal) => { keyReads.push(signal); return "cpa_0123456789abcdef0123456789abcdef"; };
	await loadCompat({ registerProvider: p => registrations.push(p) }, upstream, ownerWith(oauth, "sk-ant-oat01-owner"), undefined, { mode: "proxy", hubKey });
	assert.equal(seen.length, 1);
	assert.equal(seen[0].mode, "proxy");
	assert.equal(seen[0].origin, HUB_ORIGIN);
	assert.equal(HUB_ORIGIN, "https://cliproxy.internal.cartwmic.com");
	assert.deepEqual(await seen[0].directAuth(undefined), { apiKey: "sk-ant-oat01-owner" });
	assert.equal(registrations.length, 1);
	const key = registrations[0].auth.apiKey;
	assert.equal(registrations[0].auth.oauth, undefined, "the hub route never uses the shared Anthropic wrapper");
	assert.deepEqual(await key.check({}), { type: "api_key", source: "1Password laptop-pi" });
	const signal = new AbortController().signal;
	const stored = await key.resolve({ credential: { type: "api_key", key: "sk-ant-oat01-stored" }, signal });
	assert.deepEqual(stored, { auth: { apiKey: "cpa_0123456789abcdef0123456789abcdef" }, source: "1Password laptop-pi" }, "stored credentials are ignored");
	assert.equal(keyReads.at(-1), signal);
	await assert.rejects(key.login(), /comes from 1Password/);
	for (const bad of ["sk-ant-oat01-x", "", "cpa_short", undefined]) {
		const registered = [];
		await loadCompat({ registerProvider: p => registered.push(p) }, async (api) => api.registerProvider(provider), {}, undefined,
			{ mode: "proxy", hubKey: async () => bad });
		await assert.rejects(registered[0].auth.apiKey.resolve({ signal }), /not a cpa_ hub client key/);
	}
	assert.notEqual(registrations[0].stream, provider.stream, "the prompt guard still wraps it");
	const noLogin = [];
	await loadCompat({ registerProvider() {} }, async (_api, options) => noLogin.push(options), ownerWith([], undefined), undefined, { mode: "proxy" });
	await assert.rejects(noLogin[0].directAuth(undefined), /\/login anthropic/);
	const apiKeyOwner = [];
	await loadCompat({ registerProvider() {} }, async (_api, options) => apiKeyOwner.push(options), ownerWith(oauth, "sk-ant-api03-paid"), undefined, { mode: "proxy" });
	await assert.rejects(apiKeyOwner[0].directAuth(undefined), /OAuth access token/);
});
test("an unknown mode fails before the fork is called", async () => {
	let called = false;
	for (const mode of [undefined, "", "hub"]) {
		await assert.rejects(loadCompat({}, async () => { called = true; }, {}, undefined, { mode }), /Unexpected Claude Compat mode/);
	}
	assert.equal(called, false);
});
test("direct mode never reads the hub key", async () => {
	await loadCompat({ registerProvider() {} }, async (api) => api.registerProvider({ id: "claude-compat", auth: { oauth: {} }, stream() {}, streamSimple() {} }),
		ownerWith([], undefined), undefined, { mode: "direct", hubKey: async () => assert.fail("direct mode read the hub key") });
});
test("the hub key is a 1Password reference; models.json has no claude-compat key and no proxy provider", () => {
	assert.equal(HUB_KEY_REF, "op://developer/tb36gtnaocyezjk3dslomp64he/laptop-pi");
	const template = readFileSync(new URL("../../private_models.json.tmpl", import.meta.url), "utf8");
	const block = template.slice(template.indexOf('"claude-compat": {'), template.indexOf('"openai-codex"'));
	assert.ok(block.length > 0);
	assert.equal(block.includes('"apiKey"'), false, "direct mode must not depend on a configured key");
	assert.equal(/cpa_[0-9a-f]/.test(template), false);
	assert.equal(template.includes("claude-compat-proxy"), false);
	const settings = readFileSync(new URL("../../private_settings.json.tmpl", import.meta.url), "utf8");
	assert.match(settings, /"source": "git:github\.com\/cartwmic\/pi-claude-request-compat@[0-9a-f]{40}",\n\s*"extensions": \[\]/);
	assert.equal(settings.includes("vazzma/pi-claude-request-compat"), false);
});
test("validated full prompt differs by exactly the two documented characters", { skip: !process.env.COMPAT_PROMPT_FIXTURE }, () => {
	const original = readFileSync(process.env.COMPAT_PROMPT_FIXTURE, "utf8");
	const result = rewriteDocs(original);
	assert.equal(Buffer.byteLength(result), Buffer.byteLength(original));
	const differences = [...original].flatMap((c, i) => c !== result[i] ? [[c, result[i]]] : []);
	assert.deepEqual(differences, [["p", "P"], ["p", "P"]]);
});
