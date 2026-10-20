// Run: node --test dot_pi/private_agent/extensions/notify-owner/helpers.test.ts
//
// The core is a scripted stand-in in a scratch HOME that records its arguments; the real
// agent-alert, Herdr and doorbell are never touched. A real Pi run is the live check in README.md.
import assert from "node:assert/strict";
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { ASK_TOOL_NAME, TOOL_NAME, corePath, eligible, logPath, registerNotifyOwner, ring } from "./helpers.ts";

// A scripted child process for the injected spawner: records how it was started and lets a test fire its events.
function fakeSpawner() {
  const started: { command: string; args: string[]; options: Record<string, any> }[] = [];
  const children: { handlers: Record<string, Function>; unrefs: number; emit(event: string, arg?: unknown): void }[] = [];
  const spawnFn = (command: string, args: string[], options: Record<string, any>) => {
    started.push({ command, args, options });
    const child = { handlers: {} as Record<string, Function>, unrefs: 0, emit(event: string, arg?: unknown) { this.handlers[event]?.(arg); } };
    children.push(child);
    return { on: (event: string, handler: Function) => { child.handlers[event] = handler; }, unref: () => { child.unrefs++; } };
  };
  return { started, children, spawnFn };
}

const Type = { Object: (properties: unknown) => ({ type: "object", properties }), String: (options?: unknown) => ({ type: "string", ...(options as object) }) };

function scratch() {
  const home = mkdtempSync(join(tmpdir(), "notify-owner-"));
  const record = join(home, "calls.txt");
  const core = corePath({ HOME: home });
  mkdirSync(join(core, ".."), { recursive: true });
  writeFileSync(core, `#!/bin/sh\nprintf '%s\\n' \"$*\" >> ${record}\n`);
  chmodSync(core, 0o755);
  const env = { HOME: home, HERDR_PANE_ID: "w1:p2", HERDR_WORKSPACE_ID: "w1", PATH: process.env.PATH };
  const calls = () => (existsSync(record) ? readFileSync(record, "utf8").trim().split("\n") : []);
  return { home, env, calls, cleanup: () => rmSync(home, { recursive: true, force: true }) };
}

async function until(check: () => boolean, ms = 3000) {
  const end = Date.now() + ms;
  while (!check() && Date.now() < end) await new Promise((r) => setTimeout(r, 20));
}

function fakePi() {
  const tools: Record<string, any>[] = [];
  const handlers: Record<string, Function[]> = {};
  return { tools, handlers, registerTool: (t: Record<string, any>) => tools.push(t), on: (e: string, h: Function) => (handlers[e] ??= []).push(h) };
}

test("eligible: not in a subagent child, and only with a Herdr pane", () => {
  assert.equal(eligible({ HERDR_PANE_ID: "w1:p2" }), true);
  assert.equal(eligible({ HERDR_PANE_ID: "w1:p2", PI_SUBAGENT_CHILD: "1" }), false);
  assert.equal(eligible({}), false);
  assert.equal(eligible({ HERDR_PANE_ID: "  " }), false);
});

test("the tool is registered and its call runs emit --kind question for this pane, without waiting", async () => {
  const s = scratch();
  try {
    const pi = fakePi();
    registerNotifyOwner(pi, Type, s.env);
    const [tool] = pi.tools;
    assert.equal(tool.name, TOOL_NAME);
    assert.deepEqual(Object.keys(tool.parameters.properties), ["question"]);
    const result = await tool.execute("call-1", { question: "which database?" });
    assert.match(result.content[0].text, /Doorbell dispatched/);
    assert.equal(result.isError, undefined);
    await until(() => s.calls().length === 1);
    assert.deepEqual(s.calls(), ["emit --worker w1:p2 --kind question --context agent=pi --context workspace_id=w1"]);
    assert.doesNotMatch(s.calls()[0], /database/); // the question text is never sent
  } finally { s.cleanup(); }
});

test("an answer-ready call rings as a question, and the tool wording covers both uses", async () => {
  const s = scratch();
  try {
    const pi = fakePi();
    registerNotifyOwner(pi, Type, s.env);
    const [tool] = pi.tools;
    assert.match(tool.description, /answered a question/);
    assert.match(tool.description, /answer ready: <topic>/);
    assert.match(tool.promptSnippet, /answered a question/);
    const result = await tool.execute("c", { question: "answer ready: database choice" });
    assert.match(result.content[0].text, /question or answer summary/);
    await until(() => s.calls().length === 1);
    assert.match(s.calls()[0], /^emit --worker w1:p2 --kind question /);
    assert.doesNotMatch(s.calls()[0], /database/);
  } finally { s.cleanup(); }
});

test("an ask_user_question dialog rings; other tools, and no UI, do not", async () => {
  const s = scratch();
  try {
    const pi = fakePi();
    registerNotifyOwner(pi, Type, s.env);
    const [handler] = pi.handlers.tool_execution_start;
    handler({ toolName: "read" }, { hasUI: true });
    handler({ toolName: ASK_TOOL_NAME }, { hasUI: false });
    handler({ toolName: TOOL_NAME }, { hasUI: true }); // the tool rings itself in execute, not here
    await new Promise((r) => setTimeout(r, 300));
    assert.deepEqual(s.calls(), []);
    handler({ toolName: ASK_TOOL_NAME }, { hasUI: true });
    await until(() => s.calls().length === 1);
    assert.match(s.calls()[0], /^emit --worker w1:p2 --kind question/);
  } finally { s.cleanup(); }
});

test("a subagent child registers nothing and rings nothing", () => {
  const s = scratch();
  try {
    const pi = fakePi();
    registerNotifyOwner(pi, Type, { ...s.env, PI_SUBAGENT_CHILD: "1" });
    assert.deepEqual([pi.tools, pi.handlers], [[], {}]);
  } finally { s.cleanup(); }
});

test("outside Herdr there is no pane: nothing registered", () => {
  const s = scratch();
  try {
    const pi = fakePi();
    const { HERDR_PANE_ID: _gone, ...env } = s.env;
    registerNotifyOwner(pi, Type, env);
    assert.deepEqual([pi.tools, pi.handlers], [[], {}]);
    assert.equal(ring(env), "no-pane");
  } finally { s.cleanup(); }
});

test("agent-alert not installed: the tool says so and the worker is told to ask in its reply", async () => {
  const home = mkdtempSync(join(tmpdir(), "notify-owner-"));
  try {
    const pi = fakePi();
    registerNotifyOwner(pi, Type, { HOME: home, HERDR_PANE_ID: "w1:p2" });
    const result = await pi.tools[0].execute("c", { question: "q" });
    assert.equal(result.isError, true);
    assert.match(result.content[0].text, /not installed/);
  } finally { rmSync(home, { recursive: true, force: true }); }
});

test("a core that is not executable is reported as not installed, not as sent", async () => {
  const s = scratch();
  try {
    chmodSync(corePath(s.env), 0o644);
    assert.equal(ring(s.env), "no-core");
    const pi = fakePi();
    registerNotifyOwner(pi, Type, s.env);
    const result = await pi.tools[0].execute("c", { question: "q" });
    assert.equal(result.isError, true);
    assert.match(result.content[0].text, /not installed or not executable/);
  } finally { s.cleanup(); }
});

test("the emit is started detached, with ignored stdio, this environment, and unref'd; the tool does not wait for it", async () => {
  const s = scratch();
  try {
    const { started, children, spawnFn } = fakeSpawner();
    const pi = fakePi();
    registerNotifyOwner(pi, Type, s.env, spawnFn as never);
    const result = await pi.tools[0].execute("c", { question: "q" }); // the child never exits: execute still returned
    assert.match(result.content[0].text, /dispatched/);
    assert.equal(started.length, 1);
    assert.equal(started[0].command, corePath(s.env));
    assert.equal(started[0].options.detached, true);
    assert.equal(started[0].options.stdio, "ignore");
    assert.equal(started[0].options.env, s.env);
    assert.equal(children[0].unrefs, 1);
    assert.deepEqual(Object.keys(children[0].handlers).sort(), ["error", "exit"]); // an 'error' event can never go unhandled
  } finally { s.cleanup(); }
});

test("a failure to start the emit, or a nonzero exit, goes to the operator log; a clean exit logs nothing", () => {
  const s = scratch();
  try {
    const log = join(s.home, "operator.log");
    const env = { ...s.env, AGENT_ALERT_LOG: log };
    const { children, spawnFn } = fakeSpawner();
    ring(env, "question", spawnFn as never);
    children[0].emit("exit", 0);
    assert.equal(existsSync(log), false);
    children[0].emit("exit", 2);
    ring(env, "exited", spawnFn as never);
    children[1].emit("error", new Error("spawn EACCES"));
    const lines = readFileSync(log, "utf8").trim().split("\n");
    assert.equal(lines.length, 2);
    assert.match(lines[0], /^\S+Z notify-owner: agent-alert emit \(question\) exited with status 2; the event was not recorded$/);
    assert.match(lines[1], /notify-owner: cannot start agent-alert emit \(exited\): spawn EACCES$/);
  } finally { s.cleanup(); }
});

test("a clean quit in the TUI reports exited; reload, new, resume, fork, print, rpc and a stale ctx do not", async () => {
  const s = scratch();
  try {
    const pi = fakePi();
    registerNotifyOwner(pi, Type, s.env);
    const [shutdown] = pi.handlers.session_shutdown;
    for (const reason of ["reload", "new", "resume", "fork"]) shutdown({ reason }, { hasUI: true, mode: "tui" });
    shutdown({ reason: "quit" }, { hasUI: false, mode: "print" }); // a print-mode run is not the pane's agent
    shutdown({ reason: "quit" }, { hasUI: true, mode: "rpc" }); // nor is an RPC helper, though hasUI is true there
    shutdown({ reason: "quit" }, { hasUI: true }); // no mode: unsure, so quiet
    shutdown({ reason: "quit" }, { get mode(): string { throw new Error("stale"); } });
    await new Promise((r) => setTimeout(r, 300));
    assert.deepEqual(s.calls(), []);
    shutdown({ reason: "quit" }, { hasUI: true, mode: "tui" });
    await until(() => s.calls().length === 1);
    assert.deepEqual(s.calls(), ["emit --worker w1:p2 --kind exited --context agent=pi --context workspace_id=w1"]);
  } finally { s.cleanup(); }
});

test("without HERDR_WORKSPACE_ID the workspace context is left out", async () => {
  const s = scratch();
  try {
    const { HERDR_WORKSPACE_ID: _w, ...env } = s.env;
    assert.equal(ring(env), "sent");
    await until(() => s.calls().length === 1);
    assert.deepEqual(s.calls(), ["emit --worker w1:p2 --kind question --context agent=pi"]);
  } finally { s.cleanup(); }
});

test("the operator log path is resolved as the core does: env (with ~), then config log_path, then the default", () => {
  const home = mkdtempSync(join(tmpdir(), "notify-owner-"));
  try {
    assert.equal(logPath({ HOME: home }), join(home, ".local/state/agent-alert/agent-alert.log"));
    assert.equal(logPath({ HOME: home, AGENT_ALERT_LOG: "~/alerts.log" }), join(home, "alerts.log"));
    assert.equal(logPath({ HOME: home, AGENT_ALERT_LOG: "/var/x.log" }), "/var/x.log");
    const config = join(home, "config.json");
    writeFileSync(config, JSON.stringify({ log_path: "~/from-config.log" }));
    assert.equal(logPath({ HOME: home, AGENT_ALERT_CONFIG: config }), join(home, "from-config.log"));
    assert.equal(logPath({ HOME: home, AGENT_ALERT_CONFIG: config, AGENT_ALERT_LOG: "/env.log" }), "/env.log");
    writeFileSync(config, "not json");
    assert.equal(logPath({ HOME: home, AGENT_ALERT_CONFIG: config }), join(home, ".local/state/agent-alert/agent-alert.log"));
  } finally { rmSync(home, { recursive: true, force: true }); }
});
