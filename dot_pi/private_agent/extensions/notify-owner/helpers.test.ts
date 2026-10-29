// Run: node --test dot_pi/private_agent/extensions/notify-owner/helpers.test.ts
//
// The core is a scripted stand-in in a scratch HOME that records its arguments; the real
// agent-alert, Herdr and doorbell are never touched. A real Pi run is the live check in README.md.
import assert from "node:assert/strict";
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { ALERT_DOORS, ALERT_KINDS, ALERT_SCOPES, ASK_TOOL_NAME, TOOL_NAME, corePath, eligible, logPath, prepareNotifyArguments, registerNotifyOwner, ring, validateAlert } from "./helpers.ts";

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

const Type = {
  Object: (properties: unknown, options?: unknown) => ({ type: "object", properties, ...(options as object) }),
  String: (options?: unknown) => ({ type: "string", ...(options as object) }),
  Array: (items: unknown, options?: unknown) => ({ type: "array", items, ...(options as object) }),
  Optional: (schema: unknown) => ({ ...(schema as object), optional: true }),
};

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
    assert.deepEqual(Object.keys(tool.parameters.properties), ["kind", "summary", "scope", "attachments", "options", "recommendation", "door", "question"]);
    const result = await tool.execute("call-1", { question: "which database?" });
    assert.match(result.content[0].text, /Doorbell dispatched/);
    assert.equal(result.isError, undefined);
    await until(() => s.calls().length === 1);
    assert.deepEqual(s.calls(), ["emit --worker w1:p2 --kind question --context agent=pi --context workspace_id=w1"]);
    assert.doesNotMatch(s.calls()[0], /database/); // the question text is never sent
  } finally { s.cleanup(); }
});

test("a legacy answer-ready call (only question) still rings as a question, unchanged", async () => {
  const s = scratch();
  try {
    const pi = fakePi();
    registerNotifyOwner(pi, Type, s.env);
    const [tool] = pi.tools;
    const result = await tool.execute("c", { question: "answer ready: database choice" });
    assert.match(result.content[0].text, /question or answer summary/);
    assert.doesNotMatch(result.content[0].text, /Recorded as/);
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

const fixtures = JSON.parse(readFileSync(new URL("./alert-fixtures.json", import.meta.url), "utf8"));

for (const fixture of fixtures.valid) {
  test(`fixture valid: ${fixture.name}`, () => {
    const result = validateAlert(fixture.args);
    assert.equal(result.ok, true, JSON.stringify(result));
    assert.deepEqual((result as { alert: unknown }).alert, fixture.normalized);
  });
}

for (const fixture of fixtures.invalid) {
  test(`fixture invalid: ${fixture.name}`, () => {
    const result = validateAlert(fixture.args);
    assert.equal(result.ok, false);
    const errors = (result as { errors: string[] }).errors;
    for (const expected of fixture.errors) assert.ok(errors.some((error) => error.includes(expected)), `no error mentions ${expected}: ${errors.join(" | ")}`);
  });
}

test("validateAlert reports every problem at once, and rejects non-objects and empty calls", () => {
  const result = validateAlert({ kind: "decision", summary: "x", options: ["only"], extra: 1 });
  assert.equal(result.ok, false);
  const errors = (result as { errors: string[] }).errors;
  for (const name of ["summary", "options", "recommendation", "door", "extra"]) assert.ok(errors.some((e) => e.startsWith(name)), `${name}: ${errors.join(" | ")}`);
  for (const args of [null, "text", [], undefined]) assert.equal(validateAlert(args).ok, false);
  assert.equal(validateAlert({}).ok, false);
  assert.equal(validateAlert({ question: "   " }).ok, false);
  assert.equal(validateAlert({ question: "q", urgency: "high" }).ok, false);
});

test("validateAlert limits: summary controls and length, scope on non-reports, URL and PR attachments", () => {
  const ok = (args: object) => validateAlert(args).ok;
  assert.equal(ok({ kind: "report", summary: "line one\nline two" }), true);
  assert.equal(ok({ kind: "report", summary: "tab\there" }), false);
  assert.equal(ok({ kind: "report", summary: "x".repeat(600) }), true);
  assert.equal(ok({ kind: "report", summary: "x".repeat(601) }), false);
  assert.equal(ok({ kind: "report", summary: "ok done", scope: "forever" }), false);
  assert.equal(ok({ kind: "blocked", summary: "stuck here", scope: "workstream" }), false);
  assert.equal(ok({ kind: "blocked", summary: "stuck here", scope: "step", options: ["a", "b"] }), true);
  assert.equal(ok({ kind: "blocked", summary: "stuck here", options: ["a", "b"], recommendation: "a" }), false);
  assert.equal(ok({ kind: "report", summary: "all done", attachments: ["https://example.com/a..b", "PR owner/repo#4", "PR #5", "rel/file.md", "~/x/y.png"] }), true);
  assert.equal(ok({ kind: "report", summary: "all done", attachments: ["bad\u0000path"] }), false);
  assert.equal(ok({ kind: "report", summary: "all done", attachments: [""] }), false);
  assert.equal(ok({ kind: "question", summary: "which one?", options: ["a", " b "], recommendation: " b " }), true);
  assert.equal(ok({ kind: "question", summary: "which one?", options: ["a", "b", "c", "d", "e", "f", "g"], recommendation: "none" }), false);
});

test("the description tells drivers each kind, each scope, and what review, decision and question need", () => {
  const s = scratch();
  try {
    const pi = fakePi();
    registerNotifyOwner(pi, Type, s.env);
    const { description } = pi.tools[0];
    for (const word of [...ALERT_KINDS, ...ALERT_SCOPES, ...ALERT_DOORS]) assert.ok(description.includes(word), `description lacks ${word}`);
    assert.match(description, /'step'[^.]*merged PR[^.]*finished phase/);
    assert.match(description, /WHOLE assignment/);
    assert.match(description, /review:[^.]*LOOK AT[^.]*needs attachments/);
    assert.match(description, /question:[^.]*options and a recommendation/);
    assert.match(description, /decision:[^.]*options, a recommendation and door/);
    assert.match(description, /rings nothing/);
  } finally { s.cleanup(); }
});

test("a malformed call returns an error, one problem per line, and rings nothing", async () => {
  const s = scratch();
  try {
    const { started, spawnFn } = fakeSpawner();
    const pi = fakePi();
    registerNotifyOwner(pi, Type, s.env, spawnFn as never);
    const result = await pi.tools[0].execute("c", { kind: "decision", summary: "Merge it now?", options: ["yes", "no"] });
    assert.equal(result.isError, true);
    const lines = result.content[0].text.split("\n");
    assert.match(lines[0], /^Owner not notified/);
    assert.deepEqual(lines.slice(1).map((line: string) => line.split(":")[0]), ["recommendation", "door"]);
    assert.equal((await pi.tools[0].execute("c", {})).isError, true);
    assert.equal((await pi.tools[0].execute("c", { question: "q", kind: "report", summary: "all done" })).isError, true);
    assert.equal(started.length, 0);
  } finally { s.cleanup(); }
});

test("a valid typed call rings once with the same emit arguments as a legacy call, and says what it recorded", async () => {
  const s = scratch();
  try {
    const { started, spawnFn } = fakeSpawner();
    const pi = fakePi();
    registerNotifyOwner(pi, Type, s.env, spawnFn as never);
    const typed = await pi.tools[0].execute("c", { kind: "review", summary: "Frames are ready to look at.", attachments: ["~/tmp/frames"] });
    assert.equal(typed.isError, undefined);
    assert.match(typed.content[0].text, /^Doorbell dispatched\./);
    assert.match(typed.content[0].text, /Recorded as kind=review\.$/);
    await pi.tools[0].execute("c", { question: "which database?" });
    assert.equal(started.length, 2);
    assert.deepEqual(started[0].args, ["emit", "--worker", "w1:p2", "--kind", "question", "--context", "agent=pi", "--context", "workspace_id=w1"]);
    assert.deepEqual(started[1].args, started[0].args);
    assert.equal(started[0].args.join(" ").includes("Frames"), false); // the alert text is never sent
  } finally { s.cleanup(); }
});

// The exact call from a real session (2026-10-28): the list sent as a JSON string. Pi's schema coercion used to wrap it
// into a one-item list, so the tool said "Doorbell dispatched" while the coordinator, reading the raw call, marked it invalid.
const STRING_LIST_CALL = { kind: "report", summary: "Loop Engine PR is up; body, review and gate log attached.", attachments: '["/tmp/le-pr-body.md", "/tmp/le-sol-review-4.md", "/tmp/le-gate.log"]' };

test("prepareArguments: a list sent as a JSON string becomes a real list before Pi's schema check, and the call rings", async () => {
  const s = scratch();
  try {
    const { started, spawnFn } = fakeSpawner();
    const pi = fakePi();
    registerNotifyOwner(pi, Type, s.env, spawnFn as never);
    const tool = pi.tools[0];
    assert.equal(tool.prepareArguments, prepareNotifyArguments);
    const prepared = tool.prepareArguments(structuredClone(STRING_LIST_CALL));
    assert.deepEqual(prepared.attachments, ["/tmp/le-pr-body.md", "/tmp/le-sol-review-4.md", "/tmp/le-gate.log"]);
    assert.deepEqual(tool.prepareArguments({ kind: "question", summary: "Which one?", options: '["a", "b"]', recommendation: "a" }).options, ["a", "b"]);
    const result = await tool.execute("c", prepared);
    assert.equal(result.isError, undefined);
    assert.match(result.content[0].text, /Recorded as kind=report\.$/);
    assert.equal(started.length, 1);
    // A real list and a legacy call pass through unchanged.
    assert.deepEqual(tool.prepareArguments({ kind: "review", summary: "Look at this.", attachments: ["PR #5"] }), { kind: "review", summary: "Look at this.", attachments: ["PR #5"] });
    assert.deepEqual(tool.prepareArguments({ question: "which database?" }), { question: "which database?" });
  } finally { s.cleanup(); }
});

test("prepareArguments: a bare string, a non-list JSON string or a non-string item fails the call with what was expected, before Pi could coerce it", () => {
  for (const attachments of ["/tmp/a.md", '{"path": "/tmp/a.md"}', "[3]", 3, [3]]) {
    assert.throws(() => prepareNotifyArguments({ kind: "review", summary: "Please look at this file.", attachments }), (error: Error) => {
      const lines = error.message.split("\n");
      assert.match(lines[0], /^Owner not notified: the call is malformed/);
      assert.ok(lines.some((line) => line.startsWith("attachments")), error.message);
      return true;
    }, JSON.stringify(attachments));
  }
  assert.throws(() => prepareNotifyArguments({ kind: "report", summary: "All merged and live.", attachments: "/tmp/a.md" }), /attachments: must be an array of strings, like \["first", "second"\], or that array as a JSON string \(got a string that is not a JSON array\)/);
  // Every problem at once, as execute reports them; and a wrong-typed scalar Pi would have coerced (a number summary).
  assert.throws(() => prepareNotifyArguments({ kind: "decision", summary: "Merge it?", options: "yes or no" }), /options: must be an array[\s\S]*recommendation: required[\s\S]*door: required/);
  assert.throws(() => prepareNotifyArguments({ kind: "report", summary: 12345 }), /summary: must be a string/);
});

