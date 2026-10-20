// Run: node --test dot_pi/private_agent/extensions/notify-owner/helpers.test.ts
//
// The core is a scripted stand-in in a scratch HOME that records its arguments; the real
// agent-alert, Herdr and doorbell are never touched. A real Pi run is the live check in README.md.
import assert from "node:assert/strict";
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { ASK_TOOL_NAME, TOOL_NAME, corePath, eligible, registerNotifyOwner, ring } from "./helpers.ts";

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
    assert.match(result.content[0].text, /Owner notified/);
    assert.equal(result.isError, undefined);
    await until(() => s.calls().length === 1);
    assert.deepEqual(s.calls(), ["emit --worker w1:p2 --kind question --context agent=pi --context workspace_id=w1"]);
    assert.doesNotMatch(s.calls()[0], /database/); // the question text is never sent
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

test("a core that cannot be started never throws into the worker", async () => {
  const s = scratch();
  try {
    chmodSync(corePath(s.env), 0o644); // exists, not executable: spawn reports an error event
    assert.equal(ring(s.env), "sent");
    await new Promise((r) => setTimeout(r, 200)); // an unhandled 'error' event would have crashed the run
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
