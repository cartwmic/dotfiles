// Run: node --test dot_pi/private_agent/extensions/axon-playbook/index.test.ts
import assert from "node:assert/strict";
import { chmodSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { CUSTOM_TYPE, create, defaultScript, formatBlock, playbookInContext, runPlaybookContext } from "./index.ts";

const dir = mkdtempSync(join(tmpdir(), "axon-playbook-"));
const script = (name: string, body: string, mode = 0o755): string => {
	const path = join(dir, name);
	writeFileSync(path, `#!/bin/sh\n${body}\n`);
	chmodSync(path, mode);
	return path;
};

type Handler = (event: any, ctx?: any) => any;
const load = (options: Parameters<typeof create>[0] = {}) => {
	const handlers: Record<string, Handler> = {};
	create({ env: {}, ...options })({ on: (name: string, fn: Handler) => (handlers[name] = fn) } as any);
	return handlers;
};
const ctxWith = (branch: any[] = [], cwd = "/work/repo") => ({ cwd, sessionManager: { getBranch: () => branch } });
const injected = { id: "m1", type: "custom_message", customType: CUSTOM_TYPE };

test("script absent or not executable: nothing is injected", async () => {
	for (const path of [join(dir, "missing"), script("not-exec", "echo hi", 0o644)]) {
		const { before_agent_start } = load({ script: path });
		assert.equal(await before_agent_start!({}, ctxWith()), undefined, path);
	}
});

test("script prints text: it is injected once, as a hidden tagged message, for ctx.cwd", async () => {
	const { before_agent_start } = load({ script: script("ok", 'printf "NOTES for %s\\n" "$1"') });
	const first = await before_agent_start!({}, ctxWith([], "/work/repo"));
	assert.deepEqual(first, {
		message: { customType: CUSTOM_TYPE, content: formatBlock("NOTES for /work/repo"), display: false },
	});
	assert.equal(first.message.content, "<axon_playbook>\nNOTES for /work/repo\n</axon_playbook>");
	assert.equal(await before_agent_start!({}, ctxWith()), undefined);
	assert.equal(await before_agent_start!({}, ctxWith()), undefined);
});

test("script fails, times out, or prints nothing: nothing is injected, and it is not retried every turn", async () => {
	const counter = join(dir, "runs");
	for (const [name, body, timeoutMs] of [["fails", 'echo "partial"; exit 3', 5000], ["silent", "exit 0", 5000], ["blank", 'echo "  "', 5000], ["slow", "sleep 5; echo late", 300]] as const) {
		const { before_agent_start } = load({ script: script(name, `echo x >> ${counter}-${name}\n${body}`), timeoutMs });
		assert.equal(await before_agent_start!({}, ctxWith()), undefined, name);
		assert.equal(await before_agent_start!({}, ctxWith()), undefined, name);
		if (name !== "slow") assert.equal(readFileSync(`${counter}-${name}`, "utf8"), "x\n", `${name} ran once`);
	}
});

test("runPlaybookContext kills a script that outlives the timeout", async () => {
	const started = Date.now();
	assert.equal(await runPlaybookContext(script("hang", "sleep 5"), "/", 300), "");
	assert.ok(Date.now() - started < 3000);
});

test("a session that already holds the message (resume, fork) is not injected again", async () => {
	const { before_agent_start } = load({ script: script("held", "echo notes") });
	assert.equal(await before_agent_start!({}, ctxWith([{ id: "u1", type: "message" }, injected])), undefined);
});

test("after compaction the message is injected once more, unless the compaction kept it", async () => {
	const body = script("recompact", "echo notes");
	const compaction = (firstKeptEntryId: string) => ({ id: "c1", type: "compaction", firstKeptEntryId });
	const gone = [injected, { id: "u1", type: "message" }, compaction("u1")];
	const kept = [{ id: "u0", type: "message" }, injected, { id: "u1", type: "message" }, compaction("m1")];

	const a = load({ script: body });
	assert.ok(await a.before_agent_start!({}, ctxWith([])), "first turn");
	assert.equal(await a.before_agent_start!({}, ctxWith([injected])), undefined);
	a.session_compact!({});
	assert.ok(await a.before_agent_start!({}, ctxWith(gone)), "turn after compaction");
	assert.equal(await a.before_agent_start!({}, ctxWith(gone)), undefined);

	const b = load({ script: body });
	b.session_compact!({});
	assert.equal(await b.before_agent_start!({}, ctxWith(kept)), undefined, "kept by compaction");
});

test("playbookInContext", () => {
	assert.equal(playbookInContext([]), false);
	assert.equal(playbookInContext([injected]), true);
	assert.equal(playbookInContext([injected, { id: "c", type: "compaction", firstKeptEntryId: "zzz" }]), false);
	assert.equal(playbookInContext([injected, { id: "c", type: "compaction", firstKeptEntryId: "m1" }]), true);
	assert.equal(playbookInContext([{ id: "c", type: "compaction", firstKeptEntryId: "c" }, injected]), true);
});

test("subagent children register nothing", () => {
	assert.deepEqual(load({ env: { PI_SUBAGENT_CHILD: "1" } }), {});
});

test("a throwing session manager injects nothing", async () => {
	const { before_agent_start } = load({ script: script("boom", "echo notes") });
	const ctx = { cwd: "/", sessionManager: { getBranch: () => { throw new Error("stale"); } } };
	assert.equal(await before_agent_start!({}, ctx), undefined);
});

test("default script path is the playbook checkout's bin/playbook-context", () => {
	assert.equal(defaultScript("/home/u"), "/home/u/.local/share/agent-harness/external-skills/axon-agents-playbook/bin/playbook-context");
});
