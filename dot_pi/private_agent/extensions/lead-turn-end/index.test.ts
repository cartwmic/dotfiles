// Run: node --experimental-strip-types --disable-warning=ExperimentalWarning --test dot_pi/private_agent/extensions/lead-turn-end/index.test.ts
// The coordinator and the jobs hook are never run here: `run` is a fake that records what it was asked and answers from a table.
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { type TestContext, test } from "node:test";
import { register, type Run, type TurnEndConfig, lastStopReason, loadConfig, turnEndRefusal } from "./index.ts";

const scratch = (t: TestContext): string => {
	const dir = mkdtempSync(join(tmpdir(), "lte-"));
	t.after(() => rmSync(dir, { recursive: true, force: true }));
	return dir;
};

interface Rig {
	config: TurnEndConfig;
	calls: { command: string; args: readonly string[]; env: NodeJS.ProcessEnv }[];
	run: Run;
}

/** A coordinator checkout with a cli.ts, a state directory and a jobs hook; `answers` is what the fake gives back per command ("jobs" for python, "turn-end" for node). */
const rig = (t: TestContext, answers: { jobs?: string; turnEnd?: string }): Rig => {
	const root = scratch(t);
	const repo = join(root, "coordinator");
	mkdirSync(join(repo, "src", "coordinatord"), { recursive: true });
	writeFileSync(join(repo, "src", "coordinatord", "cli.ts"), "");
	const state = join(root, "state");
	mkdirSync(state);
	const jobsHook = join(root, "stop_running_jobs.py");
	writeFileSync(jobsHook, "");
	const calls: Rig["calls"] = [];
	const run: Run = async (command, args, env) => {
		calls.push({ command, args, env });
		if (command === "python3") return { status: 0, stdout: answers.jobs ?? "0\n" };
		return { status: 0, stdout: answers.turnEnd ?? '{"answer":"allow","reason":"x"}\n' };
	};
	return { config: { enabled: true, coordinatorRepo: repo, stateDir: state, jobsHook }, calls, run };
};

const ENV = { T3CODE_THREAD_ID: "thread:one" } as NodeJS.ProcessEnv;
const turnEndArgs = (r: Rig): readonly string[] => r.calls.find((c) => c.command !== "python3")?.args ?? [];

test("a refusal is returned, with the jobs count and the thread passed to the coordinator", async (t) => {
	const r = rig(t, { jobs: "2\n", turnEnd: '{"answer":"refuse","message":"do the work"}\n' });
	assert.equal(await turnEndRefusal({ config: r.config, env: ENV, continued: false, run: r.run }), "do the work");
	const args = turnEndArgs(r);
	assert.ok(args.includes("turn-end") && args.includes("--thread") && args.includes("thread:one"));
	assert.equal(args[args.indexOf("--jobs") + 1], "2");
	assert.ok(!args.includes("--continued"));
	const jobs = r.calls.find((c) => c.command === "python3");
	assert.equal(jobs?.env.STOP_JOBS_THREAD, "thread:one");
});

test("after a refusal the next ask carries --continued", async (t) => {
	const r = rig(t, { turnEnd: '{"answer":"let-through","reason":"x","reported":true}\n' });
	assert.equal(await turnEndRefusal({ config: r.config, env: ENV, continued: true, run: r.run }), undefined);
	assert.ok(turnEndArgs(r).includes("--continued"));
});

test("an allow, an unreadable answer and a failed command all let the end stand", async (t) => {
	const allow = rig(t, {});
	assert.equal(await turnEndRefusal({ config: allow.config, env: ENV, continued: false, run: allow.run }), undefined);
	const junk = rig(t, { turnEnd: "not json\n" });
	assert.equal(await turnEndRefusal({ config: junk.config, env: ENV, continued: false, run: junk.run }), undefined);
	const dead = rig(t, {});
	const failing: Run = async () => ({ status: null, stdout: "" });
	assert.equal(await turnEndRefusal({ config: dead.config, env: ENV, continued: false, run: failing }), undefined);
});

test("a count that cannot be read is zero jobs, not a refusal to ask", async (t) => {
	const r = rig(t, { jobs: "banana\n", turnEnd: '{"answer":"refuse","message":"m"}\n' });
	assert.equal(await turnEndRefusal({ config: r.config, env: ENV, continued: false, run: r.run }), "m");
	const args = turnEndArgs(r);
	assert.equal(args[args.indexOf("--jobs") + 1], "0");
});

test("not a T3 session, no config, switched off, or no checkout: nothing is run", async (t) => {
	const r = rig(t, { turnEnd: '{"answer":"refuse","message":"m"}\n' });
	assert.equal(await turnEndRefusal({ config: r.config, env: {}, continued: false, run: r.run }), undefined);
	assert.equal(await turnEndRefusal({ config: undefined, env: ENV, continued: false, run: r.run }), undefined);
	assert.equal(await turnEndRefusal({ config: { ...r.config, enabled: false }, env: ENV, continued: false, run: r.run }), undefined);
	assert.equal(await turnEndRefusal({ config: { ...r.config, coordinatorRepo: "/nowhere" }, env: ENV, continued: false, run: r.run }), undefined);
	assert.equal(await turnEndRefusal({ config: { ...r.config, stateDir: "/nowhere" }, env: ENV, continued: false, run: r.run }), undefined);
	assert.equal(r.calls.length, 0);
});

test("the session's own state directory wins over the config's", async (t) => {
	const r = rig(t, {});
	await turnEndRefusal({ config: r.config, env: { ...ENV, COORDINATOR_STATE_DIR: r.config.stateDir }, continued: false, run: r.run });
	assert.equal(r.calls[0]?.env.COORDINATOR_STATE_DIR, r.config.stateDir);
});

test("loadConfig reads an object and nothing else", (t) => {
	const dir = scratch(t);
	writeFileSync(join(dir, "a.json"), '{"enabled":true}');
	writeFileSync(join(dir, "b.json"), "[1]");
	writeFileSync(join(dir, "c.json"), "{");
	assert.deepEqual(loadConfig(join(dir, "a.json")), { enabled: true });
	assert.equal(loadConfig(join(dir, "b.json")), undefined);
	assert.equal(loadConfig(join(dir, "c.json")), undefined);
	assert.equal(loadConfig(join(dir, "missing.json")), undefined);
});

test("lastStopReason is the last assistant message's, and only that", () => {
	assert.equal(lastStopReason([{ role: "user" }, { role: "assistant", stopReason: "stop" }, { role: "toolResult" }]), "stop");
	assert.equal(lastStopReason([{ role: "assistant", stopReason: "stop" }, { role: "assistant", stopReason: "aborted" }]), "aborted");
	assert.equal(lastStopReason([{ role: "user" }]), undefined);
	assert.equal(lastStopReason("nope"), undefined);
});

// The wiring: a fake Pi that records handlers and sent messages. The flag is the extension's only memory.
test("a refusal is sent as a follow-up; the next end asks with --continued; a new input starts again", async (t) => {
	const r = rig(t, { turnEnd: '{"answer":"refuse","message":"keep going"}\n' });
	const handlers: Record<string, (event: unknown) => Promise<unknown>> = {};
	const sent: { text: string; options: unknown }[] = [];
	const pi = { on: (name: string, h: (e: unknown) => Promise<unknown>) => void (handlers[name] = h), sendUserMessage: (text: string, options: unknown) => void sent.push({ text, options }) };
	register(pi as never, { config: r.config, env: ENV, run: r.run });
	const clean = { messages: [{ role: "assistant", stopReason: "stop" }] };
	const continuedAsked = (): boolean[] => r.calls.filter((c) => c.command !== "python3").map((c) => c.args.includes("--continued"));

	await handlers.agent_end(clean);
	assert.deepEqual(sent, [{ text: "keep going", options: { deliverAs: "followUp" } }]);
	await handlers.input({ source: "extension" }); // our own follow-up arrives: the flag stays
	await handlers.agent_end(clean);
	assert.deepEqual(continuedAsked(), [false, true]);
	await handlers.input({ source: "rpc" }); // a message from someone else: a first end again
	await handlers.agent_end(clean);
	assert.deepEqual(continuedAsked(), [false, true, false]);
});

test("an unclean end (abort, error) is not asked about", async (t) => {
	const r = rig(t, { turnEnd: '{"answer":"refuse","message":"m"}\n' });
	const handlers: Record<string, (event: unknown) => Promise<unknown>> = {};
	const sent: unknown[] = [];
	register({ on: (n: string, h: (e: unknown) => Promise<unknown>) => void (handlers[n] = h), sendUserMessage: (m: string) => void sent.push(m) } as never, { config: r.config, env: ENV, run: r.run });
	await handlers.agent_end({ messages: [{ role: "assistant", stopReason: "aborted" }] });
	assert.equal(r.calls.length, 0);
	assert.equal(sent.length, 0);
});

test("when the answer is to let the end stand, nothing is sent", async (t) => {
	const r = rig(t, { turnEnd: '{"answer":"allow","reason":"a child is running"}\n' });
	const handlers: Record<string, (event: unknown) => Promise<unknown>> = {};
	const sent: unknown[] = [];
	register({ on: (n: string, h: (e: unknown) => Promise<unknown>) => void (handlers[n] = h), sendUserMessage: (m: string) => void sent.push(m) } as never, { config: r.config, env: ENV, run: r.run });
	await handlers.agent_end({ messages: [{ role: "assistant", stopReason: "stop" }] });
	assert.equal(sent.length, 0);
});
