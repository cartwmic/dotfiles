#!/usr/bin/env node
// Seam test for the empty-turn-retry patch. Drives the patched pi-ai
// anthropic-messages stream() against a mock Anthropic SSE server, using the
// exact degenerate shapes observed in pi session transcripts (empty text
// block / thinking-only content with rawStopReason end_turn), plus healthy
// shapes to prove no regression.
//
// Run after every pi upgrade that re-triggers the patch:
//   node ~/.local/share/pi-patches/empty-turn-retry/test.mjs
//
// Expected output:
//   empty-text:     error "Provider returned error: empty assistant turn ..."
//   thinking-only:  error "Provider returned error: empty assistant turn ..."
//   healthy-text:   done stopReason=stop content=[text]
//   healthy-tooluse: done stopReason=toolUse content=[toolCall]

import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { homedir } from "node:os";
import { createServer } from "node:http";

function locatePiAiStream() {
	const requireFromHome = createRequire(join(homedir(), "package.json"));
	const candidates = [];
	try {
		const pcaPkg = requireFromHome.resolve("@earendil-works/pi-coding-agent/package.json");
		candidates.push(join(dirname(pcaPkg), "node_modules", "@earendil-works", "pi-ai", "dist", "api", "anthropic-messages.js"));
	} catch { /* not resolvable */ }
	try {
		candidates.push(requireFromHome.resolve("@earendil-works/pi-ai/dist/api/anthropic-messages.js"));
	} catch { /* not hoisted */ }
	try {
		const npmRoot = execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim();
		candidates.push(join(npmRoot, "@earendil-works", "pi-coding-agent", "node_modules", "@earendil-works", "pi-ai", "dist", "api", "anthropic-messages.js"));
		candidates.push(join(npmRoot, "@earendil-works", "pi-ai", "dist", "api", "anthropic-messages.js"));
	} catch { /* npm not on PATH */ }
	for (const p of candidates) {
		if (p && existsSync(p)) return p;
	}
	throw new Error("pi-ai anthropic-messages.js not installed");
}

const { stream } = await import(`file://${locatePiAiStream()}`);

const model = {
	id: "glm-5.3-flash",
	api: "anthropic-messages",
	provider: "private-glm",
	baseUrl: "http://127.0.0.1:9317",
	contextWindow: 1048576,
	maxTokens: 131072,
	reasoning: true,
	input: ["text"],
	cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
};

function sseEventsFor(shape) {
	const base = [
		`event: message_start\ndata: ${JSON.stringify({ type: "message_start", message: { role: "assistant", model: "glm-5.3-flash", usage: { input_tokens: 100, output_tokens: 0 } } })}\n\n`,
	];
	if (shape === "empty-text") {
		// Exact observed shape: content_block_start text, no deltas, end_turn.
		base.push(`event: content_block_start\ndata: ${JSON.stringify({ type: "content_block_start", index: 0, content_block: { type: "text", text: "" } })}\n\n`);
		base.push(`event: content_block_stop\ndata: ${JSON.stringify({ type: "content_block_stop", index: 0 })}\n\n`);
		base.push(`event: message_delta\ndata: ${JSON.stringify({ type: "message_delta", delta: { stop_reason: "end_turn" }, usage: { input_tokens: 100, output_tokens: 0 } })}\n\n`);
	} else if (shape === "thinking-only") {
		base.push(`event: content_block_start\ndata: ${JSON.stringify({ type: "content_block_start", index: 0, content_block: { type: "thinking", thinking: "" } })}\n\n`);
		base.push(`event: content_block_delta\ndata: ${JSON.stringify({ type: "content_block_delta", index: 0, delta: { type: "thinking_delta", thinking: "reasoning..." } })}\n\n`);
		base.push(`event: content_block_stop\ndata: ${JSON.stringify({ type: "content_block_stop", index: 0 })}\n\n`);
		base.push(`event: message_delta\ndata: ${JSON.stringify({ type: "message_delta", delta: { stop_reason: "end_turn" }, usage: { input_tokens: 100, output_tokens: 0 } })}\n\n`);
	} else if (shape === "healthy-text") {
		base.push(`event: content_block_start\ndata: ${JSON.stringify({ type: "content_block_start", index: 0, content_block: { type: "text", text: "" } })}\n\n`);
		base.push(`event: content_block_delta\ndata: ${JSON.stringify({ type: "content_block_delta", index: 0, delta: { type: "text_delta", text: "All done." } })}\n\n`);
		base.push(`event: content_block_stop\ndata: ${JSON.stringify({ type: "content_block_stop", index: 0 })}\n\n`);
		base.push(`event: message_delta\ndata: ${JSON.stringify({ type: "message_delta", delta: { stop_reason: "end_turn" }, usage: { input_tokens: 100, output_tokens: 5 } })}\n\n`);
	} else if (shape === "healthy-tooluse") {
		base.push(`event: content_block_start\ndata: ${JSON.stringify({ type: "content_block_start", index: 0, content_block: { type: "tool_use", name: "bash", id: "t1" } })}\n\n`);
		base.push(`event: content_block_delta\ndata: ${JSON.stringify({ type: "content_block_delta", index: 0, delta: { type: "input_json_delta", partial_json: "{\"command\":\"ls\"}" } })}\n\n`);
		base.push(`event: content_block_stop\ndata: ${JSON.stringify({ type: "content_block_stop", index: 0 })}\n\n`);
		base.push(`event: message_delta\ndata: ${JSON.stringify({ type: "message_delta", delta: { stop_reason: "tool_use" }, usage: { input_tokens: 100, output_tokens: 5 } })}\n\n`);
	}
	base.push(`event: message_stop\ndata: ${JSON.stringify({ type: "message_stop" })}\n\n`);
	return base;
}

// Mock server: pi-ai builds the URL itself (baseUrl + /v1/messages), so the
// requested shape travels on an x-shape header instead of a query param.
const server = createServer((req, res) => {
	const shape = req.headers["x-shape"] || "empty-text";
	res.writeHead(200, { "content-type": "text/event-stream", "transfer-encoding": "chunked" });
	for (const ev of sseEventsFor(shape)) res.write(ev);
	res.end();
});
await new Promise((r) => server.listen(9317, "127.0.0.1", r));

let failures = 0;
async function run(shape, expectError) {
	const context = { messages: [{ role: "user", content: [{ type: "text", text: "hi" }] }], tools: [] };
	const events = [];
	try {
		for await (const ev of stream(model, context, { apiKey: "sk-test", headers: { "x-shape": shape } })) events.push(ev);
	} catch (e) {
		failures += 1;
		console.log(`${shape}: UNEXPECTED throw: ${e.message}`);
		return;
	}
	const errEv = events.find((e) => e.type === "error");
	const done = events.find((e) => e.type === "done");
	if (expectError) {
		if (errEv && (errEv.error?.errorMessage || "").includes("Provider returned error: empty assistant turn")) {
			console.log(`${shape}: OK — retryable error surfaced`);
		} else {
			failures += 1;
			console.log(`${shape}: FAIL — expected retryable error, got events=[${events.map((e) => e.type).join(",")}]`);
		}
	} else {
		if (done && !errEv) {
			const types = (done.message?.content || []).map((c) => c.type).join(",");
			console.log(`${shape}: OK — done stopReason=${done.message?.stopReason} content=[${types}]`);
		} else {
			failures += 1;
			console.log(`${shape}: FAIL — expected normal completion, got events=[${events.map((e) => e.type).join(",")}]`);
		}
	}
}

await run("empty-text", true);
await run("thinking-only", true);
await run("healthy-text", false);
await run("healthy-tooluse", false);
server.close();
process.exit(failures === 0 ? 0 : 1);
