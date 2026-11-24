// Run: node --experimental-strip-types --disable-warning=ExperimentalWarning --test dot_pi/private_agent/extensions/lead-turn-end/index.test.ts
// The coordinator and the jobs hook are never run here: `run` is a fake that records what it was asked and answers from a table.
import assert from "node:assert/strict";
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { type TestContext, test } from "node:test";
import { checkTurnEnd, register, type Run, type TurnEndConfig, lastStopReason, loadConfig } from "./index.ts";

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

/** The refusal text the coordinator gave, if it refused. */
const turnEndRefusal = async (options: Parameters<typeof checkTurnEnd>[0]): Promise<string | undefined> => {
	const check = await checkTurnEnd(options);
	return check.kind === "answered" ? check.refusal : undefined;
};

const adapterLines = (r: Rig): Record<string, unknown>[] => {
	const path = join(r.config.stateDir as string, "t3-hook", "turn-end-adapter.jsonl");
	return existsSync(path) ? readFileSync(path, "utf8").trim().split("\n").map((l) => JSON.parse(l) as Record<string, unknown>) : [];
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

test("an allow lets the end stand and writes nothing", async (t) => {
	const allow = rig(t, {});
	assert.equal(await turnEndRefusal({ config: allow.config, env: ENV, continued: false, run: allow.run }), undefined);
	assert.deepEqual(adapterLines(allow), []);
});

test("a check that cannot run lets the end stand and writes one line saying why", async (t) => {
	const cases: [string, Run, string][] = [
		["a timeout", async () => ({ status: null, stdout: "" }), "timed out"],
		["output that is not JSON", async (command) => ({ status: 0, stdout: command === "python3" ? "0\n" : "not json\n" }), "no readable answer (exit 0)"],
		["a crash", async (command) => ({ status: command === "python3" ? 0 : 1, stdout: command === "python3" ? "0\n" : "" }), "no readable answer (exit 1)"],
		["a missing t3 turn-end command", async (command) => ({ status: command === "python3" ? 0 : 2, stdout: command === "python3" ? "0\n" : "usage: coordinator ...\n" }), "no readable answer (exit 2)"],
		["an answer with no answer field", async (command) => ({ status: 0, stdout: command === "python3" ? "0\n" : '{"message":"x"}\n' }), "no readable answer (exit 0)"],
	];
	for (const [name, fake, reason] of cases) {
		const r = rig(t, {});
		const check = await checkTurnEnd({ config: r.config, env: ENV, continued: false, run: fake });
		assert.equal(check.kind, "failed", name);
		const lines = adapterLines(r);
		assert.equal(lines.length, 1, name);
		const line = lines[0] as Record<string, unknown>;
		assert.deepEqual([line.outcome, line.cause, line.thread, line.adapter], ["allowed", "check-failed", "thread:one", "pi-extension"], name);
		assert.ok(String(line.reason).includes(reason), `${name}: ${String(line.reason)}`);
		assert.equal(typeof line.duration_ms, "number", name);
		assert.ok(!Number.isNaN(Date.parse(String(line.ts))), name);
	}
});

test("a missing checkout or state directory is a failed check too, once a thread and config are there", async (t) => {
	const r = rig(t, {});
	const noCheckout = await checkTurnEnd({ config: { ...r.config, coordinatorRepo: "/nowhere" }, env: ENV, continued: false, run: r.run });
	assert.equal(noCheckout.kind, "failed");
	assert.ok(String(adapterLines(r)[0]?.reason).startsWith("coordinator checkout not found"));
	const gone = join(scratch(t), "no-state-yet");
	const noState = await checkTurnEnd({ config: { ...r.config, stateDir: gone }, env: ENV, continued: false, run: r.run });
	assert.equal(noState.kind, "failed");
	assert.ok(String(JSON.parse(readFileSync(join(gone, "t3-hook", "turn-end-adapter.jsonl"), "utf8").trim()).reason).startsWith("state directory not found"));
	assert.equal(r.calls.length, 0);
});

test("a count that cannot be read is zero jobs, not a refusal to ask", async (t) => {
	const r = rig(t, { jobs: "banana\n", turnEnd: '{"answer":"refuse","message":"m"}\n' });
	assert.equal(await turnEndRefusal({ config: r.config, env: ENV, continued: false, run: r.run }), "m");
	const args = turnEndArgs(r);
	assert.equal(args[args.indexOf("--jobs") + 1], "0");
});

test("not a T3 session, no config, or switched off: nothing is run and nothing is written", async (t) => {
	const r = rig(t, { turnEnd: '{"answer":"refuse","message":"m"}\n' });
	assert.equal(await turnEndRefusal({ config: r.config, env: {}, continued: false, run: r.run }), undefined);
	assert.equal(await turnEndRefusal({ config: undefined, env: ENV, continued: false, run: r.run }), undefined);
	assert.equal(await turnEndRefusal({ config: { ...r.config, enabled: false }, env: ENV, continued: false, run: r.run }), undefined);
	assert.equal(r.calls.length, 0);
	assert.deepEqual(adapterLines(r), []);
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

// The wiring: a fake Pi that records handlers and sent messages. The refusal the turn has had is the extension's only memory.
const fakePi = (): { handlers: Record<string, (event: unknown) => Promise<unknown>>; sent: { text: string; options: unknown }[]; pi: never } => {
	const handlers: Record<string, (event: unknown) => Promise<unknown>> = {};
	const sent: { text: string; options: unknown }[] = [];
	const pi = { on: (name: string, h: (e: unknown) => Promise<unknown>) => void (handlers[name] = h), sendUserMessage: (text: string, options: unknown) => void sent.push({ text, options }) };
	return { handlers, sent, pi: pi as never };
};
const clean = { messages: [{ role: "assistant", stopReason: "stop" }] };

test("a refusal is sent as a follow-up; the next end asks with --continued; a real user input starts again", async (t) => {
	const r = rig(t, { turnEnd: '{"answer":"refuse","message":"keep going"}\n' });
	const { handlers, sent, pi } = fakePi();
	register(pi, { config: r.config, env: ENV, run: r.run });
	const continuedAsked = (): boolean[] => r.calls.filter((c) => c.command !== "python3").map((c) => c.args.includes("--continued"));

	await handlers.agent_end(clean);
	assert.deepEqual(sent, [{ text: "keep going", options: { deliverAs: "followUp" } }]);
	await handlers.input({ source: "extension", text: "keep going" }); // our own follow-up arrives: the refusal stands
	await handlers.agent_end(clean);
	assert.deepEqual(continuedAsked(), [false, true]);
	await handlers.input({ source: "rpc", text: "a new request" }); // a real user input: a first end again
	await handlers.agent_end(clean);
	assert.deepEqual(continuedAsked(), [false, true, false]);
	assert.equal(sent.length, 2);
});

test("a second refusal is not issued in the same user turn, even when the coordinator asks for one", async (t) => {
	const r = rig(t, { turnEnd: '{"answer":"refuse","message":"keep going"}\n' });
	const { handlers, sent, pi } = fakePi();
	register(pi, { config: r.config, env: ENV, run: r.run });
	await handlers.agent_end(clean);
	await handlers.agent_end(clean); // refused again by the (stuck) coordinator: still one message
	await handlers.agent_end(clean);
	assert.equal(sent.length, 1);
	const lines = adapterLines(r);
	assert.equal(lines.length, 2);
	assert.deepEqual(lines.map((l) => [l.outcome, l.cause, l.adapter]), [["allowed", "after-refusal", "pi-extension"], ["allowed", "after-refusal", "pi-extension"]]);
	assert.equal(typeof lines[0]?.duration_ms, "number");
});

test("neither the refusal text arriving as an input nor an extension message clears the refusal", async (t) => {
	const r = rig(t, { turnEnd: '{"answer":"refuse","message":"keep going"}\n' });
	const { handlers, sent, pi } = fakePi();
	register(pi, { config: r.config, env: ENV, run: r.run });
	await handlers.agent_end(clean);
	await handlers.input({ source: "interactive", text: "keep going" }); // the refusal replayed under another source
	await handlers.input({ source: "extension", text: "something another extension said" });
	await handlers.agent_end(clean);
	assert.equal(sent.length, 1);
	await handlers.input({ source: "interactive", text: "do something else" });
	await handlers.agent_end(clean);
	assert.equal(sent.length, 2);
});

test("an end that arrives while the check for the last one is still running is not asked about twice", async (t) => {
	const r = rig(t, {});
	let release: () => void = () => {};
	const gate = new Promise<void>((resolve) => void (release = resolve));
	const slow: Run = async (command, args, env, ms) => {
		await gate;
		return r.run(command, args, env, ms).then((out) => (command === "python3" ? out : { status: 0, stdout: '{"answer":"refuse","message":"once"}\n' }));
	};
	const { handlers, sent, pi } = fakePi();
	register(pi, { config: r.config, env: ENV, run: slow });
	const first = handlers.agent_end(clean);
	const second = handlers.agent_end(clean);
	release();
	await Promise.all([first, second]);
	assert.equal(sent.length, 1);
});

test("the default export reads config.json beside the module and runs the real command", async (t) => {
	const root = scratch(t);
	const repo = join(root, "coordinator");
	mkdirSync(join(repo, "src", "coordinatord"), { recursive: true });
	writeFileSync(join(repo, "src", "coordinatord", "cli.ts"), 'console.log(JSON.stringify({ answer: "refuse", message: "from the real command" }));\n');
	const state = join(root, "state");
	mkdirSync(state);
	const ext = join(root, "ext");
	mkdirSync(ext);
	copyFileSync(new URL("./index.ts", import.meta.url), join(ext, "index.ts"));
	writeFileSync(join(ext, "config.json"), JSON.stringify({ enabled: true, coordinatorRepo: repo, stateDir: state }));
	const { default: extension } = (await import(join(ext, "index.ts"))) as { default: (pi: never) => void };
	const { handlers, sent, pi } = fakePi();
	const before = process.env.T3CODE_THREAD_ID;
	process.env.T3CODE_THREAD_ID = "thread:default-export";
	t.after(() => void (before === undefined ? delete process.env.T3CODE_THREAD_ID : (process.env.T3CODE_THREAD_ID = before)));
	extension(pi);
	assert.deepEqual(Object.keys(handlers).sort(), ["agent_end", "input"]);
	await handlers.agent_end(clean);
	assert.deepEqual(sent, [{ text: "from the real command", options: { deliverAs: "followUp" } }]);
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
