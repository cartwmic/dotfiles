// Real installed observer + upstream Compat + guard; scripted transport only.
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { execFileSync } from "node:child_process";
import { createPiObserverRunner } from "../../dot_pi/private_agent/extensions/learnings-monitor/worker.mjs";
import { createLearningStore } from "../../dot_pi/private_agent/extensions/learnings-monitor/store.mjs";

const moduleRoot = execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim();
const sdk = await import(pathToFileURL(path.join(moduleRoot, "@earendil-works/pi-coding-agent/dist/index.js")));
const scratch = await fs.mkdtemp(path.join(os.tmpdir(), "compat-observer-proof-"));
const agentDir = path.join(scratch, "agent"), cwd = path.join(scratch, "work"), sessionDir = path.join(scratch, "sessions");
await Promise.all([agentDir, cwd, sessionDir].map(p => fs.mkdir(p, { recursive: true })));
await fs.writeFile(path.join(agentDir, "auth.json"), JSON.stringify({ "anthropic": {
	type: "oauth", access: "sk-ant-oat-synthetic-test-only", refresh: "disabled", expires: Date.now() + 3600000,
} }), { mode: 0o600 });
const compat = path.join(os.homedir(), ".pi/agent/git/github.com/vazzma/pi-claude-request-compat/src/extension.js");
const guard = process.env.COMPAT_GUARD ?? path.join(os.homedir(), ".pi/agent/extensions/claude-compat-guard/index.ts");
const oldFetch = globalThis.fetch;
const oldAgentDir = process.env.PI_CODING_AGENT_DIR;
process.env.PI_CODING_AGENT_DIR = agentDir;
await fs.mkdir(path.join(agentDir, "git/github.com/vazzma"), { recursive: true });
await fs.symlink(path.dirname(path.dirname(compat)), path.join(agentDir, "git/github.com/vazzma/pi-claude-request-compat"));
let calls = 0;
globalThis.fetch = async (input, init) => {
	const url = new URL(input instanceof Request ? input.url : String(input));
	assert.equal(url.origin, "https://api.anthropic.com", "unexpected network origin");
	if (url.pathname === "/api/claude_cli/bootstrap") return Response.json({ oauth_account: { account_uuid: "scripted-account" } });
	assert.equal(url.pathname, "/v1/messages");
	const payload = JSON.parse(Buffer.from(init.body).toString());
	assert.equal(payload.model, "claude-haiku-4-5");
	assert.ok(payload.system[0].text.startsWith("x-anthropic-billing-header:"));
	assert.ok(payload.system.some(b => b.text?.includes("read-only workflow observer")));
	calls++;
	const events = [
		{ type: "message_start", message: { id: "msg_scripted", type: "message", role: "assistant", model: payload.model,
			content: [], stop_reason: null, stop_sequence: null, usage: { input_tokens: 100, output_tokens: 0 } } },
		{ type: "content_block_start", index: 0, content_block: { type: "text", text: "" } },
		{ type: "content_block_delta", index: 0, delta: { type: "text_delta", text: '{"proposals":[]}' } },
		{ type: "content_block_stop", index: 0 },
		{ type: "message_delta", delta: { stop_reason: "end_turn", stop_sequence: null }, usage: { output_tokens: 10 } },
		{ type: "message_stop" },
	];
	return new Response(events.map(e => "event: " + e.type + "\ndata: " + JSON.stringify(e) + "\n\n").join(""),
		{ headers: { "content-type": "text/event-stream" } });
};
const runner = createPiObserverRunner({
	sdk, agentDir, sessionDir,
	store: createLearningStore({ root: path.join(scratch, "store") }),
	providerExtensionLoadout: { "claude-compat": [guard] },
	resourceLoaderFactory: ({ cwd, agentDir, settingsManager, extensionPaths }) => {
		const loader = new sdk.DefaultResourceLoader({ cwd, agentDir, settingsManager,
			additionalExtensionPaths: extensionPaths, noExtensions: true, noSkills: true, noPromptTemplates: true,
			noThemes: true, noContextFiles: true, systemPrompt: "You are the read-only workflow observer. Return JSON only." });
		const reload = loader.reload.bind(loader);
		loader.reload = async () => { await reload(); assert.deepEqual(loader.getExtensions().errors, []); };
		return loader;
	},
});
try {
	const result = await runner.run({
		sourceId: "compat-proof", cwd, batchId: "batch-proof", pendingBatchIds: ["pending-proof"],
		payload: { source: { id: "compat-proof", label: "Scripted proof" }, evidence: [{
			id: "evidence-proof", summary: "Completed read-only workflow.", outcome: "completed",
			provenance: { pointer: "test://proof", availability: "available" },
		}] }, explicit: false, focus: null, modelOverride: null,
		primaryModel: { provider: "claude-compat", id: "claude-haiku-4-5" },
	});
	assert.deepEqual(JSON.parse(result.text), { proposals: [] });
	assert.equal(calls, 1);
	assert.deepEqual((await runner.stats("compat-proof")).providerExtensions, [guard]);
	assert.equal(JSON.parse(await fs.readFile(path.join(agentDir, "auth.json"), "utf8"))["claude-compat"], undefined);
	console.log("PASS real SDK observer uses installed upstream Compat + guard; scripted response completes; 0 live sends");
} finally {
	await runner.close();
	globalThis.fetch = oldFetch;
	if (oldAgentDir === undefined) delete process.env.PI_CODING_AGENT_DIR;
	else process.env.PI_CODING_AGENT_DIR = oldAgentDir;
	await fs.rm(scratch, { recursive: true, force: true });
}
