// Tests for the hindsight extension pure helpers.
// Run: node --test dot_pi/private_agent/extensions/hindsight/index.test.ts
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as http from "node:http";
import * as os from "node:os";
import * as path from "node:path";
import { test } from "node:test";
import { recall, retain } from "./client.ts";
import { applyEnvOverrides, DEFAULTS, loadEnabled, parseConfig, saveEnabled } from "./config.ts";
import {
	buildRecallQuery,
	deriveProjectTag,
	extractText,
	findRepoRoot,
	formatMemoryBlock,
	lastAssistantText,
	RECALL_CONTEXT_CHARS,
	MEMORY_CLOSE,
	MEMORY_OPEN,
	messagesToTranscript,
	sanitizeTag,
	stripMemoryBlocks,
} from "./content.ts";
import hindsight, { parseToggle } from "./index.ts";

// --- config ---

test("parseConfig: empty -> DEFAULTS", () => {
	assert.deepEqual(parseConfig(undefined), DEFAULTS);
	assert.deepEqual(parseConfig("not json"), DEFAULTS);
});

test("parseConfig: overrides + trailing-slash trim + clamps", () => {
	const c = parseConfig(
		JSON.stringify({ apiUrl: "https://h.example.com/", retainEveryNTurns: 0, recallBudget: "bad" }),
	);
	assert.equal(c.apiUrl, "https://h.example.com");
	assert.equal(c.retainEveryNTurns, 1); // clamped to >= 1
	assert.equal(c.recallBudget, "mid"); // invalid -> default
});

test("applyEnvOverrides: url/token/flags", () => {
	const c = applyEnvOverrides(DEFAULTS, {
		HINDSIGHT_API_URL: "https://x.example.com/",
		HINDSIGHT_API_TOKEN: "tok",
		HINDSIGHT_AUTO_RETAIN: "false",
		HINDSIGHT_DEBUG: "true",
	} as NodeJS.ProcessEnv);
	assert.equal(c.apiUrl, "https://x.example.com");
	assert.equal(c.apiToken, "tok");
	assert.equal(c.autoRetain, false);
	assert.equal(c.debug, true);
});

test("applyEnvOverrides: subagent children never auto-recall or auto-retain", () => {
	const c = applyEnvOverrides(DEFAULTS, { PI_SUBAGENT_CHILD: "1" } as NodeJS.ProcessEnv);
	assert.equal(c.autoRecall, false);
	assert.equal(c.autoRetain, false);
	const top = applyEnvOverrides(DEFAULTS, {} as NodeJS.ProcessEnv);
	assert.equal(top.autoRecall, true);
	assert.equal(top.autoRetain, true);
});

test("loadEnabled/saveEnabled: sidecar override", () => {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "hs-"));
	assert.equal(loadEnabled(dir, true), true); // no state file -> default
	saveEnabled(dir, false);
	assert.equal(loadEnabled(dir, true), false); // override wins
	fs.rmSync(dir, { recursive: true, force: true });
});

// --- tags ---

test("sanitizeTag: lowercase, collapse, trim", () => {
	assert.equal(sanitizeTag("My Repo!!"), "my-repo");
	assert.equal(sanitizeTag("--a__b--"), "a__b");
});

test("deriveProjectTag: from cwd basename outside git", () => {
	assert.equal(deriveProjectTag("/nonexistent-hs/x/code/Chezmoi/"), "project:chezmoi");
	assert.equal(deriveProjectTag(undefined), null);
});

test("deriveProjectTag: repo subdirectories and linked worktrees share the main repo tag", () => {
	const base = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "hs-git-")));
	const main = path.join(base, "My-Repo");
	fs.mkdirSync(path.join(main, "src", "deep"), { recursive: true });
	const git = (...args: string[]) => execFileSync("git", args, { cwd: main, stdio: "ignore" });
	git("init", "-q");
	git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "--allow-empty", "-m", "init");
	const wt = path.join(base, "My-Repo-wt-feature-20261003T000000Z");
	git("worktree", "add", "-q", wt);
	fs.mkdirSync(path.join(wt, "pkg"));
	assert.equal(findRepoRoot(path.join(main, "src", "deep")), main);
	assert.equal(findRepoRoot(path.join(wt, "pkg")), main);
	assert.equal(deriveProjectTag(path.join(main, "src", "deep")), "project:my-repo");
	assert.equal(deriveProjectTag(path.join(wt, "pkg")), "project:my-repo");
	const alias = path.join(base, "Alias");
	fs.symlinkSync(main, alias);
	assert.equal(deriveProjectTag(path.join(alias, "src")), "project:my-repo");
	fs.rmSync(base, { recursive: true, force: true });
});

// --- recall query + block ---

test("buildRecallQuery: strips prior blocks + truncates", () => {
	const q = buildRecallQuery(`hello ${MEMORY_OPEN}\nold\n${MEMORY_CLOSE} world`, 800);
	// block removal leaves the surrounding spaces; that's fine for a query
	assert.equal(q, "hello  world");
});

test("buildRecallQuery: truncation", () => {
	assert.equal(buildRecallQuery("abcdef", 3), "abc");
});

test("buildRecallQuery: prompt first, then the start of the previous reply", () => {
	const reply = `We changed the escalation rule. ${"x".repeat(500)}`;
	const q = buildRecallQuery("is this rule fine?", 800, { previousReply: reply });
	assert.ok(q.startsWith("User: is this rule fine?\n\nContext (previous assistant reply): We changed the escalation rule."));
	assert.equal(q.length, "User: is this rule fine?\n\nContext (previous assistant reply): ".length + RECALL_CONTEXT_CHARS);
});

test("buildRecallQuery: extension-sent prompts use only the context", () => {
	const q = buildRecallQuery("Your session was compacted. continue what you were doing", 800, {
		previousReply: "Hindsight recall fix in progress",
		includePrompt: false,
	});
	assert.equal(q, "Context (previous assistant reply): Hindsight recall fix in progress");
	// Without any previous reply, fall back to the prompt.
	assert.equal(buildRecallQuery("continue", 800, { includePrompt: false }), "continue");
});

test("buildRecallQuery: memory blocks in the previous reply are stripped", () => {
	const q = buildRecallQuery("next", 800, { previousReply: `${MEMORY_OPEN}\nold\n${MEMORY_CLOSE}\nreal reply` });
	assert.equal(q, "User: next\n\nContext (previous assistant reply): real reply");
});

test("lastAssistantText: newest assistant message with text", () => {
	const entries = [
		{ type: "message", message: { role: "assistant", content: [{ type: "text", text: "older" }] } },
		{ type: "message", message: { role: "assistant", content: [{ type: "text", text: "newest" }] } },
		{ type: "message", message: { role: "assistant", content: [{ type: "toolCall", name: "bash" }] } },
		{ type: "message", message: { role: "user", content: "question" } },
		{ type: "custom", message: undefined },
	];
	assert.equal(lastAssistantText(entries), "newest");
	assert.equal(lastAssistantText([]), "");
});

// --- client request bodies ---

test("recall and retain send the expected request bodies", async () => {
	const bodies: Array<{ url?: string; body: Record<string, unknown> }> = [];
	const server = http.createServer((req, res) => {
		let data = "";
		req.on("data", (c) => (data += c));
		req.on("end", () => {
			bodies.push({ url: req.url, body: JSON.parse(data) });
			res.setHeader("content-type", "application/json");
			res.end(JSON.stringify({ results: [{ id: "m1", text: "remembered", type: "observation" }] }));
		});
	});
	await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
	const port = (server.address() as { port: number }).port;
	const cfg = { ...DEFAULTS, apiUrl: `http://127.0.0.1:${port}`, bankId: "b" };
	try {
		const results = await recall(cfg, "q");
		assert.deepEqual(results, [{ id: "m1", text: "remembered", type: "observation" }]);
		await retain(cfg, [{ content: "t", tags: ["session:s", "project:p"], observation_scopes: "shared" }], "op-1");
	} finally {
		server.close();
	}
	assert.equal(bodies[0].url, "/v1/default/banks/b/memories/recall");
	assert.deepEqual(bodies[0].body.include, { entities: null });
	assert.equal(bodies[1].url, "/v1/default/banks/b/memories");
	assert.deepEqual(bodies[1].body, {
		items: [{ content: "t", tags: ["session:s", "project:p"], observation_scopes: "shared" }],
		async: true,
		operation_id: "op-1",
	});
});

test("formatMemoryBlock: wraps non-empty, empty when no results", () => {
	assert.equal(formatMemoryBlock([]), "");
	assert.equal(formatMemoryBlock([{ id: "1", text: "   " }]), "");
	const b = formatMemoryBlock([
		{ id: "1", text: "Uses pnpm" },
		{ id: "2", text: "Prefers tabs" },
	]);
	assert.ok(b.startsWith(MEMORY_OPEN));
	assert.ok(b.endsWith(MEMORY_CLOSE));
	assert.ok(b.includes("- Uses pnpm"));
	assert.ok(b.includes("- Prefers tabs"));
});

// --- strip ---

test("stripMemoryBlocks: removes spans, collapses blank lines", () => {
	const t = `a\n${MEMORY_OPEN}\nx\n${MEMORY_CLOSE}\n\n\nb`;
	assert.equal(stripMemoryBlocks(t), "a\n\nb");
	assert.equal(stripMemoryBlocks("plain"), "plain");
});

// --- transcript ---

test("extractText: string + block array + tool calls", () => {
	assert.equal(extractText({ role: "user", content: "hi" }, false), "hi");
	assert.equal(
		extractText({ role: "assistant", content: [{ type: "text", text: "yo" }] }, false),
		"yo",
	);
	const withTool = extractText(
		{ role: "assistant", content: [{ type: "toolCall", name: "bash", arguments: { cmd: "ls" } }] },
		true,
	);
	assert.ok(withTool.includes("[tool: bash"));
	assert.equal(
		extractText({ role: "assistant", content: [{ type: "toolCall", name: "bash" }] }, false),
		"",
	);
});

test("messagesToTranscript: filters roles, drops injected blocks", () => {
	const msgs = [
		{ role: "user", content: "fix the bug" },
		{ role: "custom", customType: "hindsight_memories", content: "should be dropped" },
		{ role: "assistant", content: `done ${MEMORY_OPEN}\nx\n${MEMORY_CLOSE}` },
		{ role: "system", content: "ignored role" },
	];
	const t = messagesToTranscript(msgs, { roles: ["user", "assistant"], includeToolCalls: false });
	assert.equal(t, "User: fix the bug\n\nAssistant: done");
	assert.ok(!t.includes("hindsight_memories"));
	assert.ok(!t.includes("ignored role"));
});

// --- toggle ---

test("parseToggle", () => {
	assert.equal(parseToggle(""), "status");
	assert.equal(parseToggle("status"), "status");
	assert.equal(parseToggle("on"), "on");
	assert.equal(parseToggle("OFF"), "off");
	assert.equal(parseToggle("toggle"), "toggle");
	assert.equal(parseToggle("wat"), "invalid");
});

// --- auto-retain through the extension's own hooks ---

type Req = { url?: string; body: Record<string, unknown> };

/** Load the extension against a scripted Hindsight server. respond() may delay or drop. */
async function withExtension(
	respond: (req: Req, res: http.ServerResponse) => void,
	body: (h: {
		requests: Req[];
		emit: (name: string, event: unknown, sessionId: string) => Promise<unknown>;
	}) => Promise<void>,
	hasUI = true,
) {
	const requests: Req[] = [];
	const server = http.createServer((req, res) => {
		let data = "";
		req.on("data", (c) => (data += c));
		req.on("end", () => {
			const r = { url: req.url, body: data ? JSON.parse(data) : {} };
			requests.push(r);
			respond(r, res);
		});
	});
	await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
	const saved = { url: process.env.HINDSIGHT_API_URL, child: process.env.PI_SUBAGENT_CHILD };
	process.env.HINDSIGHT_API_URL = `http://127.0.0.1:${(server.address() as { port: number }).port}`;
	delete process.env.PI_SUBAGENT_CHILD;
	const handlers = new Map<string, (event: unknown, ctx: unknown) => Promise<unknown> | unknown>();
	hindsight({ on: (name: string, fn: never) => handlers.set(name, fn), registerCommand: () => {} } as never);
	const emit = async (name: string, event: unknown, sessionId: string) =>
		handlers.get(name)?.(event, {
			hasUI,
			sessionManager: { getSessionId: () => sessionId, getCwd: () => "/nonexistent-hs/proj", getBranch: () => [] },
		});
	try {
		await body({ requests, emit });
	} finally {
		server.closeAllConnections();
		server.close();
		if (saved.url === undefined) delete process.env.HINDSIGHT_API_URL;
		else process.env.HINDSIGHT_API_URL = saved.url;
		if (saved.child !== undefined) process.env.PI_SUBAGENT_CHILD = saved.child;
	}
}

const run = (n: number) => ({ messages: [{ role: "user", content: `q${n}` }, { role: "assistant", content: `a${n}` }] });
const turns = (from: number, to: number) =>
	Array.from({ length: to - from + 1 }, (_, i) => `User: q${from + i}\n\nAssistant: a${from + i}`).join("\n\n");
const item = (r: Req) => (r.body.items as Array<Record<string, unknown>>)[0];
const ok = (_r: Req, res: http.ServerResponse) => res.end("{}");
const settle = () => new Promise((r) => setTimeout(r, 50));

test("auto-retain appends each run once, per session, never replacing history", async () => {
	await withExtension(ok, async ({ requests, emit }) => {
		for (let n = 1; n <= 10; n++) await emit("agent_end", run(n), "s1");
		await settle();
		assert.equal(requests.length, 1, "one retain after 10 cycles");
		assert.equal(item(requests[0]).update_mode, "append");
		assert.equal(item(requests[0]).content, turns(1, 10));
		assert.equal(typeof requests[0].body.operation_id, "string");
		for (let n = 11; n <= 12; n++) await emit("agent_end", run(n), "s1");
		await emit("agent_end", run(13), "s2"); // session switch ships s1's buffer
		await settle();
		assert.equal(item(requests[1]).document_id, "pi-session-s1");
		assert.equal(item(requests[1]).content, turns(11, 12));
		await emit("session_shutdown", {}, "s2");
		assert.equal(item(requests[2]).document_id, "pi-session-s2");
		assert.equal(item(requests[2]).content, turns(13, 13));
		assert.equal(requests.length, 3);
		assert.equal(new Set(requests.map((r) => r.body.operation_id)).size, 3);
	});
});

test("shutdown waits for an in-flight retain and then ships the rest", async () => {
	const done: string[] = [];
	await withExtension(
		(r, res) =>
			setTimeout(() => {
				done.push(item(r).content as string);
				res.end("{}");
			}, 150),
		async ({ requests, emit }) => {
			for (let n = 1; n <= 10; n++) await emit("agent_end", run(n), "s1"); // cadence send starts
			await emit("agent_end", run(11), "s1");
			await emit("session_shutdown", {}, "s1");
			assert.deepEqual(done, [turns(1, 10), turns(11, 11)], "both acknowledged before shutdown returned");
			assert.equal(requests.length, 2);
		},
	);
});

test("a lost acknowledgement is retried with the same operation_id", async () => {
	let first = true;
	await withExtension(
		(_r, res) => {
			if (first) {
				first = false;
				res.socket?.destroy(); // server accepted, response lost
				return;
			}
			res.end("{}");
		},
		async ({ requests, emit }) => {
			for (let n = 1; n <= 10; n++) await emit("agent_end", run(n), "s1");
			await settle();
			await emit("agent_end", run(11), "s1");
			await emit("session_shutdown", {}, "s1");
			assert.equal(requests.length, 3, "failed send, retry, then the new batch");
			assert.equal(requests[1].body.operation_id, requests[0].body.operation_id);
			assert.equal(item(requests[1]).content, turns(1, 10));
			assert.notEqual(requests[2].body.operation_id, requests[0].body.operation_id);
			assert.equal(item(requests[2]).content, turns(11, 11));
		},
	);
});

test("a batch the server keeps rejecting is dropped after 3 attempts", async () => {
	await withExtension(
		(r, res) => {
			res.statusCode = item(r).content === turns(1, 10) ? 400 : 200;
			res.end("{}");
		},
		async ({ requests, emit }) => {
			for (let n = 1; n <= 10; n++) await emit("agent_end", run(n), "s1");
			await settle();
			await emit("session_shutdown", {}, "s1");
			await emit("agent_end", run(11), "s1");
			await emit("session_shutdown", {}, "s1");
			const bad = requests.filter((r) => item(r).content === turns(1, 10));
			assert.equal(bad.length, 3);
			assert.equal(item(requests.at(-1) as Req).content, turns(11, 11));
		},
	);
});

test("an outage keeps the batch and delivers it, in order, once the server recovers", async () => {
	let outage = 3;
	await withExtension(
		(_r, res) => {
			res.statusCode = outage-- > 0 ? 503 : 200;
			res.end("{}");
		},
		async ({ requests, emit }) => {
			for (let n = 1; n <= 10; n++) await emit("agent_end", run(n), "s1");
			await settle();
			await emit("session_shutdown", {}, "s1");
			await emit("session_shutdown", {}, "s1");
			await emit("agent_end", run(11), "s1");
			await emit("session_shutdown", {}, "s1"); // server is back
			const delivered = requests.slice(3).map((r) => item(r).content);
			assert.deepEqual(delivered, [turns(1, 10), turns(11, 11)]);
			assert.equal(requests[3].body.operation_id, requests[0].body.operation_id);
		},
	);
});

test("headless runs (no UI) neither recall nor retain", async () => {
	await withExtension(
		ok,
		async ({ requests, emit }) => {
			assert.equal(await emit("before_agent_start", { prompt: "hello" }, "w1"), undefined);
			for (let n = 1; n <= 10; n++) await emit("agent_end", run(n), "w1");
			await emit("session_shutdown", {}, "w1");
			assert.equal(requests.length, 0);
		},
		false,
	);
});
