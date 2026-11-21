// Run: node --experimental-strip-types --disable-warning=ExperimentalWarning --test dot_pi/private_agent/extensions/coordinator-helper-gate/index.test.ts
// The coordinator checkout is a scratch directory holding a stub hook.ts; the real one is never started here.
import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import extension, { type GateConfig, type HelperCall, gateReason, loadConfig, loadsCoordinatorSession, toolCallHandler } from "./index.ts";

// The stub reads the call on stdin and records it with the environment it was given. STUB_MODE picks the answer.
const STUB_HOOK = `
import { appendFileSync, readFileSync } from "node:fs";
const stdin = readFileSync(0, "utf8");
appendFileSync(process.env.STUB_RECORD, JSON.stringify({ argv: process.argv.slice(2), stdin: JSON.parse(stdin), state: process.env.COORDINATOR_STATE_DIR ?? null, t3: process.env.T3CODE_THREAD_ID ?? null }) + "\\n");
const mode = process.env.STUB_MODE ?? "allow";
if (mode === "block") process.stdout.write(JSON.stringify({ block: true, reason: "refused by the stub: declare a seat" }));
if (mode === "no-block") process.stdout.write(JSON.stringify({ block: false }));
if (mode === "garbage") process.stdout.write("not json at all");
if (mode === "fail") { process.stderr.write("stub broke\\n"); process.exit(3); }
`;

interface Rig {
	root: string;
	repo: string;
	state: string;
	record: string;
	config: GateConfig;
	env: NodeJS.ProcessEnv;
	recorded: () => { argv: string[]; stdin: Record<string, unknown>; state: string | null; t3: string | null }[];
	logLines: () => string[];
}

const rig = (mode: string, env: NodeJS.ProcessEnv = {}): Rig => {
	const root = mkdtempSync(join(tmpdir(), "chg-"));
	const repo = join(root, "coordinator");
	const state = join(root, "state");
	mkdirSync(join(repo, "src", "t3-hook"), { recursive: true });
	mkdirSync(state, { recursive: true });
	writeFileSync(join(repo, "src", "t3-hook", "hook.ts"), STUB_HOOK);
	const record = join(root, "record.jsonl");
	const log = join(state, "t3-hook", "helper-gate.log");
	return {
		root,
		repo,
		state,
		record,
		config: { enabled: true, coordinatorRepo: repo, stateDir: state },
		env: { PATH: process.env.PATH, STUB_RECORD: record, STUB_MODE: mode, ...env },
		recorded: () => (existsSync(record) ? readFileSync(record, "utf8").trim().split("\n").map((line) => JSON.parse(line)) : []),
		logLines: () => (existsSync(log) ? readFileSync(log, "utf8").trim().split("\n") : []),
	};
};

const call = (over: Partial<HelperCall> = {}): HelperCall => ({ toolName: "subagent", toolCallId: "call-1", input: { agent: "worker", task: "do it" }, cwd: "/work/here", sessionId: "sess-1", model: "anthropic/claude-opus-5-5", ...over });
const gate = (r: Rig, over: Partial<HelperCall> = {}, extra: { argv?: string[]; config?: GateConfig | undefined } = {}) =>
	gateReason(call(over), { config: "config" in extra ? extra.config : r.config, env: r.env, argv: extra.argv ?? ["node", "pi"] });

test("a refusal from the hook is the block reason; the hook gets the call, the cwd and the session's model, and the state directory", () => {
	const r = rig("block");
	assert.equal(gate(r), "refused by the stub: declare a seat");
	const [seen] = r.recorded();
	assert.deepEqual(seen?.argv, ["--pi"]);
	assert.deepEqual(seen?.stdin, { session_id: "sess-1", tool_use_id: "call-1", cwd: "/work/here", session_model: "anthropic/claude-opus-5-5", tool_input: { agent: "worker", task: "do it" } });
	assert.equal(r.recorded().length, 1);
});

test("a hook that says nothing lets the call through", () => {
	const r = rig("allow");
	assert.equal(gate(r), undefined);
	assert.equal(r.recorded().length, 1);
	assert.deepEqual(r.logLines(), []);
});

test("only the subagent tool is asked about", () => {
	const r = rig("block");
	assert.equal(gate(r, { toolName: "bash", input: { command: "ls" } }), undefined);
	assert.equal(gate(r, { toolName: "read" }), undefined);
	assert.deepEqual(r.recorded(), []);
});

test("scope: the state directory is the environment's when set, else the config's; no T3 variable is needed, and one does not change the answer", () => {
	const plain = rig("block");
	assert.equal(gate(plain), "refused by the stub: declare a seat");
	assert.equal(plain.recorded()[0]?.state, plain.state, "a session with no COORDINATOR_STATE_DIR (plain pi) gets the config's directory");
	assert.equal(plain.recorded()[0]?.t3, null, "and there is no T3CODE_THREAD_ID in it, so none is required");

	const lead = rig("block");
	const leadState = join(lead.root, "lead-state");
	mkdirSync(leadState);
	lead.env = { ...lead.env, COORDINATOR_STATE_DIR: leadState, T3CODE_THREAD_ID: "thread-9" };
	assert.equal(gate(lead), "refused by the stub: declare a seat");
	assert.equal(lead.recorded()[0]?.state, leadState, "pi-lead's own COORDINATOR_STATE_DIR wins");
	assert.equal(lead.recorded()[0]?.t3, "thread-9");
});

test("stands down in the coordinator's own session (its -e argument), and only there", () => {
	const session = "/home/u/git/coordinator/src/coordinator-session/index.ts";
	assert.equal(loadsCoordinatorSession(["node", "pi", "--model", "m", "-e", session]), true);
	assert.equal(loadsCoordinatorSession(["node", "pi", "--extension", session]), true);
	assert.equal(loadsCoordinatorSession(["node", "pi", `--extension=${session}`]), true);
	assert.equal(loadsCoordinatorSession(["node", "pi", "-e", "/x/other-session/index.ts"]), false);
	assert.equal(loadsCoordinatorSession(["node", "pi", "-e", "/x/coordinator-session/helper-gate.ts"]), false);
	assert.equal(loadsCoordinatorSession(["node", "pi", session]), false, "a path that is not the value of -e does not count");
	assert.equal(loadsCoordinatorSession(["node", "pi", "--mode", "rpc", "--extension", "/t3/cache/t3-mcp.ts"]), false, "T3's own extension argument is not the coordinator's");

	const r = rig("block");
	assert.equal(gate(r, {}, { argv: ["node", "pi", "-e", session] }), undefined);
	assert.deepEqual(r.recorded(), [], "the hook is not run a second time");
	assert.equal(gate(r, {}, { argv: ["node", "pi", "--mode", "rpc", "--extension", "/t3/cache/t3-mcp.ts"] }), "refused by the stub: declare a seat", "a T3 session still gets the gate");
});

test("fails open and quietly where the coordinator is not set up", () => {
	const r = rig("block");
	assert.equal(gate(r, {}, { config: undefined }), undefined, "no config");
	assert.equal(gate(r, {}, { config: { ...r.config, enabled: false } }), undefined, "switched off in the config");
	assert.equal(gate(r, {}, { config: { stateDir: r.state } }), undefined, "no checkout named");
	assert.equal(gate(r, {}, { config: { ...r.config, coordinatorRepo: join(r.root, "nowhere") } }), undefined, "no checkout on disk");
	mkdirSync(join(r.root, "src-less"));
	assert.equal(gate(r, {}, { config: { ...r.config, coordinatorRepo: join(r.root, "src-less") } }), undefined, "a checkout with no hook.ts");
	const noState = rig("block");
	assert.equal(gate(noState, {}, { config: { ...noState.config, stateDir: join(noState.root, "no-state") } }), undefined, "no state directory");
	assert.equal(existsSync(join(noState.root, "no-state")), false, "and none is made");
	assert.deepEqual([...r.recorded(), ...noState.recorded()], [], "the hook never ran in any of these");
});

test("fails open on a hook that fails, answers nothing readable or cannot start, and adds one line to the coordinator's helper-gate log", () => {
	for (const mode of ["fail", "garbage", "no-block"]) {
		const r = rig(mode);
		assert.equal(gate(r), undefined, mode);
		const lines = r.logLines();
		assert.equal(lines.length, 1, mode);
		const entry = JSON.parse(lines[0] ?? "{}") as Record<string, unknown>;
		assert.deepEqual(Object.keys(entry).sort(), ["at", "call", "kind", "model", "session", "what"]);
		assert.equal(entry.session, "sess-1");
		assert.equal(entry.call, "call-1");
		assert.equal(entry.kind, "worker");
		assert.match(String(entry.what), /^skipped: the gate could not run \(/);
	}
});

test("a spawn error and a hook that throws allow the call and are logged", () => {
	const r = rig("allow");
	const options = { config: r.config, env: r.env, argv: ["node", "pi"] };
	assert.equal(gateReason(call(), { ...options, run: () => ({ stdout: "", failure: "spawn node ENOENT" }) }), undefined);
	assert.equal(gateReason(call(), { ...options, run: () => ({ stdout: "", failure: "spawnSync node ETIMEDOUT" }) }), undefined);
	assert.equal(gateReason(call(), { ...options, run: () => { throw new Error("boom\nsecond line"); } }), undefined);
	assert.deepEqual(r.logLines().map((line) => (JSON.parse(line) as { what: string }).what), [
		"skipped: the gate could not run (spawn node ENOENT)",
		"skipped: the gate could not run (spawnSync node ETIMEDOUT)",
		"skipped: the gate could not run (boom)",
	]);
});

test("loadConfig reads the rendered file and gives undefined for a missing, broken or non-object one", () => {
	const dir = mkdtempSync(join(tmpdir(), "chg-cfg-"));
	const write = (text: string): string => {
		const file = join(dir, `c${Math.random()}.json`);
		writeFileSync(file, text);
		return file;
	};
	assert.deepEqual(loadConfig(write('{"enabled":true,"coordinatorRepo":"/r","stateDir":"/s"}')), { enabled: true, coordinatorRepo: "/r", stateDir: "/s" });
	for (const bad of ["not json", "[]", "3", "null"]) assert.equal(loadConfig(write(bad)), undefined, bad);
	assert.equal(loadConfig(join(dir, "missing.json")), undefined);
});

test("the handler gives the hook the session's id, cwd and model, and blocks with its reason", async () => {
	const r = rig("block");
	const handler = toolCallHandler({ config: r.config, env: r.env, argv: ["node", "pi"] });
	const ctx = { cwd: "/w", sessionManager: { getSessionId: () => "s-7" }, model: { provider: "p", id: "m" } };
	assert.deepEqual(await handler({ toolName: "subagent", toolCallId: "c-7", input: { agent: "worker" } }, ctx), { block: true, reason: "refused by the stub: declare a seat" });
	assert.deepEqual(r.recorded()[0]?.stdin, { session_id: "s-7", tool_use_id: "c-7", cwd: "/w", session_model: "p/m", tool_input: { agent: "worker" } });
	assert.equal(await handler({ toolName: "read", toolCallId: "c-8", input: {} }, ctx), undefined);
	const quiet = rig("allow");
	assert.equal(await toolCallHandler({ config: quiet.config, env: quiet.env, argv: ["node", "pi"] })({ toolName: "subagent", toolCallId: "c", input: {} }, { cwd: "/w", sessionManager: { getSessionId: () => "s" } }), undefined);
});

test("the extension registers one tool_call handler and nothing else; with no config.json beside it (the source tree) it lets everything through", async () => {
	const seen: string[] = [];
	let handler: ((event: unknown, ctx: unknown) => Promise<unknown>) | undefined;
	extension({ on: (name: string, fn: typeof handler) => { seen.push(name); handler = fn; } } as never);
	assert.deepEqual(seen, ["tool_call"]);
	const ctx = { cwd: "/w", sessionManager: { getSessionId: () => "s" }, model: { provider: "p", id: "m" } };
	assert.equal(await handler?.({ toolName: "subagent", toolCallId: "c", input: { agent: "worker" } }, ctx), undefined);
});
