import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { guardProvider, rewriteContext, rewriteDocs } from "./guard.mjs";
import { loadCompat } from "./load.mjs";

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
	await loadCompat(pi, api => { api.registerProvider(provider); api.registerCommand("upstream-status", {}); }, {});
	assert.equal(registrations.length, 1);
	assert.notEqual(registrations[0].stream, provider.stream);
	assert.notEqual(registrations[0].streamSimple, provider.streamSimple);
	assert.equal(registrations[0].auth.oauth.isSubscription, true);
	assert.equal(commands[0][0], "upstream-status");
	await assert.rejects(loadCompat(pi, api => api.registerProvider({ id: "other" }), {}), /Expected the pinned/);
});
test("validated full prompt differs by exactly the two documented characters", { skip: !process.env.COMPAT_PROMPT_FIXTURE }, () => {
	const original = readFileSync(process.env.COMPAT_PROMPT_FIXTURE, "utf8");
	const result = rewriteDocs(original);
	assert.equal(Buffer.byteLength(result), Buffer.byteLength(original));
	const differences = [...original].flatMap((c, i) => c !== result[i] ? [[c, result[i]]] : []);
	assert.deepEqual(differences, [["p", "P"], ["p", "P"]]);
});
