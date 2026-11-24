// Run: node --experimental-strip-types --disable-warning=ExperimentalWarning --test dot_pi/private_agent/extensions/coordinator-helper-gate/index.test.ts
// The coordinator checkout is a scratch directory holding a stub src/coordinator-session/helper-gate.ts; the real one is never loaded here.
// What the real helper-gate.ts does with the hook (spawn it, fail open, log) is the coordinator's own and is tested in that repo.
import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { type TestContext, test } from "node:test";
import extension, { type GateConfig, type HelperCall, beforeAgentStartHandler, firstPromptRules, gateReason, loadConfig, loadsCoordinatorSession, toolCallHandler } from "./index.ts";

// The stub has the shape of the coordinator's helperGateReason: (call, env, stateDir) => reason | undefined. It records what it was given.
// The mode comes from env.STUB_MODE: "block" refuses, "allow" says nothing, "throw" throws. Like the real one, it answers nothing for a tool other than subagent.
const STUB_GATE = `
import { appendFileSync } from "node:fs";
export function helperGateReason(call, env, stateDir) {
	appendFileSync(env.STUB_RECORD, JSON.stringify({ call, state: stateDir, t3: env.T3CODE_THREAD_ID ?? null }) + "\\n");
	if (call.toolName !== "subagent") return undefined;
	if (env.STUB_MODE === "throw") throw new Error("stub gate broke");
	return env.STUB_MODE === "block" ? "refused by the stub: declare a seat" : undefined;
}
`;

/** A directory under the temp dir that is removed when the test ends, whether it passed or failed. */
const scratch = (t: TestContext, prefix: string): string => {
	const dir = mkdtempSync(join(tmpdir(), prefix));
	t.after(() => rmSync(dir, { recursive: true, force: true }));
	return dir;
};

interface Rig {
	root: string;
	repo: string;
	state: string;
	record: string;
	config: GateConfig;
	env: NodeJS.ProcessEnv;
	recorded: () => { call: HelperCall; state: string; t3: string | null }[];
	/** The lines the extension wrote to the guard log (the rig points AGENT_HARNESS_GUARD_LOG at a scratch file). */
	guardLog: () => Record<string, unknown>[];
}

const rig = (t: TestContext, mode: string, env: NodeJS.ProcessEnv = {}, gateSource: string = STUB_GATE): Rig => {
	const root = scratch(t, "chg-");
	const repo = join(root, "coordinator");
	const state = join(root, "state");
	mkdirSync(join(repo, "src", "coordinator-session"), { recursive: true });
	mkdirSync(state, { recursive: true });
	writeFileSync(join(repo, "src", "coordinator-session", "helper-gate.ts"), gateSource);
	const record = join(root, "record.jsonl");
	return {
		root,
		repo,
		state,
		record,
		config: { enabled: true, coordinatorRepo: repo, stateDir: state },
		env: { PATH: process.env.PATH, STUB_RECORD: record, STUB_MODE: mode, AGENT_HARNESS_GUARD_LOG: join(root, "guard.jsonl"), ...env },
		guardLog: () => (existsSync(join(root, "guard.jsonl")) ? readFileSync(join(root, "guard.jsonl"), "utf8").trim().split("\n").map((line) => JSON.parse(line)) : []),
		recorded: () => (existsSync(record) ? readFileSync(record, "utf8").trim().split("\n").map((line) => JSON.parse(line)) : []),
	};
};

const call = (over: Partial<HelperCall> = {}): HelperCall => ({ toolName: "subagent", toolCallId: "call-1", input: { agent: "worker", task: "do it" }, cwd: "/work/here", sessionId: "sess-1", model: "anthropic/claude-opus-5-5", ...over });
const gate = (r: Rig, over: Partial<HelperCall> = {}, extra: { argv?: string[]; config?: GateConfig | undefined } = {}) =>
	gateReason(call(over), { config: "config" in extra ? extra.config : r.config, env: r.env, argv: extra.argv ?? ["node", "pi"] });

test("a refusal from the coordinator's gate is the block reason; it gets the call, the cwd, the session's model and the state directory", async (t) => {
	const r = rig(t, "block");
	assert.equal(await gate(r), "refused by the stub: declare a seat");
	assert.deepEqual(r.recorded(), [{ call: call(), state: r.state, t3: null }]);
});

test("a gate that says nothing lets the call through", async (t) => {
	const r = rig(t, "allow");
	assert.equal(await gate(r), undefined);
	assert.equal(r.recorded().length, 1);
});

test("a tool other than subagent is passed to the gate, which lets it through", async (t) => {
	const r = rig(t, "block");
	assert.equal(await gate(r, { toolName: "bash", input: { command: "ls" } }), undefined);
});

test("scope: the state directory is the environment's when set, else the config's; no T3 variable is needed, and one does not change the answer", async (t) => {
	const plain = rig(t, "block");
	assert.equal(await gate(plain), "refused by the stub: declare a seat");
	assert.equal(plain.recorded()[0]?.state, plain.state, "a session with no COORDINATOR_STATE_DIR (plain pi) gets the config's directory");
	assert.equal(plain.recorded()[0]?.t3, null, "and there is no T3CODE_THREAD_ID in it, so none is required");

	const lead = rig(t, "block");
	const leadState = join(lead.root, "lead-state");
	mkdirSync(leadState);
	lead.env = { ...lead.env, COORDINATOR_STATE_DIR: leadState, T3CODE_THREAD_ID: "thread-9" };
	assert.equal(await gate(lead), "refused by the stub: declare a seat");
	assert.equal(lead.recorded()[0]?.state, leadState, "pi-lead's own COORDINATOR_STATE_DIR wins");
	assert.equal(lead.recorded()[0]?.t3, "thread-9");
});

test("stands down in the coordinator's own session (its -e argument), and only there", async (t) => {
	const session = "/home/u/git/coordinator/src/coordinator-session/index.ts";
	assert.equal(loadsCoordinatorSession(["node", "pi", "--model", "m", "-e", session]), true);
	assert.equal(loadsCoordinatorSession(["node", "pi", "--extension", session]), true);
	assert.equal(loadsCoordinatorSession(["node", "pi", `--extension=${session}`]), true);
	assert.equal(loadsCoordinatorSession(["node", "pi", "-e", "/x/other-session/index.ts"]), false);
	assert.equal(loadsCoordinatorSession(["node", "pi", "-e", "/x/coordinator-session/helper-gate.ts"]), false);
	assert.equal(loadsCoordinatorSession(["node", "pi", session]), false, "a path that is not the value of -e does not count");
	assert.equal(loadsCoordinatorSession(["node", "pi", "--mode", "rpc", "--extension", "/t3/cache/t3-mcp.ts"]), false, "T3's own extension argument is not the coordinator's");

	const r = rig(t, "block");
	assert.equal(await gate(r, {}, { argv: ["node", "pi", "-e", session] }), undefined);
	assert.deepEqual(r.recorded(), [], "the gate is not asked a second time");
	assert.equal(await gate(r, {}, { argv: ["node", "pi", "--mode", "rpc", "--extension", "/t3/cache/t3-mcp.ts"] }), "refused by the stub: declare a seat", "a T3 session still gets the gate");
});

test("fails open and quietly where the coordinator is not set up", async (t) => {
	const r = rig(t, "block");
	assert.equal(await gate(r, {}, { config: undefined }), undefined, "no config");
	assert.equal(await gate(r, {}, { config: { ...r.config, enabled: false } }), undefined, "switched off in the config");
	assert.equal(await gate(r, {}, { config: { stateDir: r.state } }), undefined, "no checkout named");
	assert.equal(await gate(r, {}, { config: { ...r.config, coordinatorRepo: join(r.root, "nowhere") } }), undefined, "no checkout on disk");
	mkdirSync(join(r.root, "src-less"));
	assert.equal(await gate(r, {}, { config: { ...r.config, coordinatorRepo: join(r.root, "src-less") } }), undefined, "a checkout with no helper-gate.ts (an old one)");
	const noState = rig(t, "block");
	assert.equal(await gate(noState, {}, { config: { ...noState.config, stateDir: join(noState.root, "no-state") } }), undefined, "no state directory");
	assert.equal(existsSync(join(noState.root, "no-state")), false, "and none is made");
	assert.deepEqual([...r.recorded(), ...noState.recorded()], [], "the gate never ran in any of these");
});

test("fails open on a gate file that cannot be loaded, holds no helperGateReason, or throws", async (t) => {
	assert.equal(await gate(rig(t, "block", {}, "export const x = (")), undefined, "a file that does not parse");
	assert.equal(await gate(rig(t, "block", {}, 'throw new Error("at load");')), undefined, "a file that throws when loaded");
	assert.equal(await gate(rig(t, "block", {}, "export const other = 1;")), undefined, "a file with no helperGateReason");
	assert.equal(await gate(rig(t, "throw")), undefined, "a gate that throws");
	const r = rig(t, "block");
	assert.equal(await gateReason(call(), { config: r.config, env: r.env, argv: ["node", "pi"], load: async () => { throw new Error("no loader"); } }), undefined, "a loader that rejects");
});

test("the gate file is loaded from the configured checkout, not from anywhere else", async (t) => {
	const r = rig(t, "block");
	const loaded: string[] = [];
	const reason = await gateReason(call(), { config: r.config, env: r.env, argv: ["node", "pi"], load: async (file) => { loaded.push(file); return () => "from the loader"; } });
	assert.equal(reason, "from the loader");
	assert.deepEqual(loaded, [join(r.repo, "src", "coordinator-session", "helper-gate.ts")]);
});

test("loadConfig reads the rendered file and gives undefined for a missing, broken or non-object one", (t) => {
	const dir = scratch(t, "chg-cfg-");
	const write = (text: string): string => {
		const file = join(dir, `c${Math.random()}.json`);
		writeFileSync(file, text);
		return file;
	};
	assert.deepEqual(loadConfig(write('{"enabled":true,"coordinatorRepo":"/r","stateDir":"/s"}')), { enabled: true, coordinatorRepo: "/r", stateDir: "/s" });
	for (const bad of ["not json", "[]", "3", "null"]) assert.equal(loadConfig(write(bad)), undefined, bad);
	assert.equal(loadConfig(join(dir, "missing.json")), undefined);
});

test("the handler gives the gate the session's id, cwd and model, and blocks with its reason", async (t) => {
	const r = rig(t, "block");
	const handler = toolCallHandler({ config: r.config, env: r.env, argv: ["node", "pi"] });
	const ctx = { cwd: "/w", sessionManager: { getSessionId: () => "s-7" }, model: { provider: "p", id: "m" } };
	assert.deepEqual(await handler({ toolName: "subagent", toolCallId: "c-7", input: { agent: "worker" } }, ctx), { block: true, reason: "refused by the stub: declare a seat" });
	assert.deepEqual(r.recorded()[0]?.call, { toolName: "subagent", toolCallId: "c-7", input: { agent: "worker" }, cwd: "/w", sessionId: "s-7", model: "p/m" });
	assert.equal(await handler({ toolName: "read", toolCallId: "c-8", input: {} }, ctx), undefined);
	const quiet = rig(t, "allow");
	assert.equal(await toolCallHandler({ config: quiet.config, env: quiet.env, argv: ["node", "pi"] })({ toolName: "subagent", toolCallId: "c", input: {} }, { cwd: "/w", sessionManager: { getSessionId: () => "s" } }), undefined);
});

test("the extension registers a tool_call handler and a before_agent_start handler and nothing else; with no config.json beside it (the source tree) both let everything through", async () => {
	const seen: string[] = [];
	const handlers = new Map<string, (event: unknown, ctx: unknown) => Promise<unknown>>();
	extension({ on: (name: string, fn: (event: unknown, ctx: unknown) => Promise<unknown>) => { seen.push(name); handlers.set(name, fn); } } as never);
	assert.deepEqual(seen, ["tool_call", "before_agent_start"]);
	const ctx = { cwd: "/w", sessionManager: { getSessionId: () => "s" }, model: { provider: "p", id: "m" } };
	assert.equal(await handlers.get("tool_call")?.({ toolName: "subagent", toolCallId: "c", input: { agent: "worker" } }, ctx), undefined);
	assert.equal(await handlers.get("before_agent_start")?.({ prompt: "Kind: build" }, ctx), undefined);
});

// The stub has the shape of the coordinator's firstPromptMessage: (prompt, env, stateDir) => message text | undefined.
const STUB_PROMPT_GATE = `
import { appendFileSync } from "node:fs";
export function firstPromptMessage(prompt, env, stateDir) {
	appendFileSync(env.STUB_RECORD, JSON.stringify({ prompt, state: stateDir }) + "\\n");
	if (env.STUB_MODE === "throw") throw new Error("stub broke");
	return /^Kind: build/m.test(prompt.prompt) ? "rules for build" : undefined;
}
`;

test("the first prompt of a session gets the coordinator's rules for its kind as a hidden message, once", async (t) => {
	const r = rig(t, "tell", {}, STUB_PROMPT_GATE);
	const handler = beforeAgentStartHandler({ config: r.config, env: r.env, argv: ["node", "pi"] });
	const ctx = { cwd: "/w", sessionManager: { getSessionId: () => "s-9" } };
	assert.deepEqual(await handler({ prompt: "Seat: builder\nKind: build\n" }, ctx), { message: { customType: "playbook-door", content: "rules for build", display: false } });
	assert.deepEqual(r.recorded()[0], { prompt: { session_id: "s-9", prompt: "Seat: builder\nKind: build\n", cwd: "/w" }, state: r.state });
	assert.equal(await handler({ prompt: "Kind: build" }, ctx), undefined);
	assert.equal(r.recorded().length, 1);
});

test("a first prompt with no kind, an older coordinator checkout, a throwing function and the daemon's own session all tell nothing", async (t) => {
	const ctx = { cwd: "/w", sessionManager: { getSessionId: () => "s" } };
	const plain = rig(t, "tell", {}, STUB_PROMPT_GATE);
	assert.equal(await beforeAgentStartHandler({ config: plain.config, env: plain.env, argv: ["node", "pi"] })({ prompt: "hello" }, ctx), undefined);
	const old = rig(t, "tell", {}, "export const unrelated = 1;\n");
	assert.equal(await firstPromptRules({ sessionId: "s", prompt: "Kind: build", cwd: "/w" }, { config: old.config, env: old.env, argv: ["node", "pi"] }), undefined);
	const broken = rig(t, "throw", {}, STUB_PROMPT_GATE);
	assert.equal(await firstPromptRules({ sessionId: "s", prompt: "Kind: build", cwd: "/w" }, { config: broken.config, env: broken.env, argv: ["node", "pi"] }), undefined);
	const own = rig(t, "tell", {}, STUB_PROMPT_GATE);
	assert.equal(await firstPromptRules({ sessionId: "s", prompt: "Kind: build", cwd: "/w" }, { config: own.config, env: own.env, argv: ["node", "pi", "-e", "/r/src/coordinator-session/index.ts"] }), undefined);
	const off = rig(t, "tell", {}, STUB_PROMPT_GATE);
	assert.equal(await firstPromptRules({ sessionId: "s", prompt: "Kind: build", cwd: "/w" }, { config: { ...off.config, enabled: false }, env: off.env, argv: ["node", "pi"] }), undefined);
	assert.equal(await firstPromptRules({ sessionId: "s", prompt: "Kind: build", cwd: "/w" }, { config: undefined, env: off.env, argv: ["node", "pi"] }), undefined);
});

test("a first-prompt delivery that fails writes one door-failed line; a prompt with nothing to tell, an older checkout and a switched-off gate write none", async (t) => {
	const ctx = { cwd: "/w", sessionManager: { getSessionId: () => "s-fail" } };
	const broken = rig(t, "throw", {}, STUB_PROMPT_GATE);
	assert.equal(await beforeAgentStartHandler({ config: broken.config, env: broken.env, argv: ["node", "pi"] })({ prompt: "Seat: builder\nKind: build SECRET-VALUE" }, ctx), undefined);
	const [line, ...more] = broken.guardLog();
	assert.equal(more.length, 0);
	assert.deepEqual({ action: line.action, outcome: line.outcome, run: line.run, adapter: line.adapter, door: line.door }, { action: "door-failed", outcome: "failed", run: "s-fail", adapter: "pi", door: "brief" });
	assert.match(String(line.reason), /could not be delivered: stub broke/);
	assert.match(String(line.ts), /^\d{4}-\d\d-\d\dT/);
	assert.ok(!JSON.stringify(line).includes("SECRET-VALUE"), "the prompt is never logged");

	const unloadable = rig(t, "tell", {}, 'throw new Error("at load");');
	await firstPromptRules({ sessionId: "s-load", prompt: "Kind: build", cwd: "/w" }, { config: unloadable.config, env: unloadable.env, argv: ["node", "pi"] });
	assert.equal(unloadable.guardLog().length, 1, "a file that cannot be loaded");

	const quiet = rig(t, "tell", {}, STUB_PROMPT_GATE);
	await firstPromptRules({ sessionId: "s", prompt: "hello", cwd: "/w" }, { config: quiet.config, env: quiet.env, argv: ["node", "pi"] });
	await firstPromptRules({ sessionId: "s", prompt: "Kind: build", cwd: "/w" }, { config: { ...quiet.config, enabled: false }, env: quiet.env, argv: ["node", "pi"] });
	const old = rig(t, "tell", {}, "export const unrelated = 1;\n");
	await firstPromptRules({ sessionId: "s", prompt: "Kind: build", cwd: "/w" }, { config: old.config, env: old.env, argv: ["node", "pi"] });
	assert.deepEqual([...quiet.guardLog(), ...old.guardLog()], []);
});
