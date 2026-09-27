import test from "node:test";
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { renderOverview, runOverviewPane } from "../src/pane.mjs";
import { PALETTE_FIXTURE } from "../src/theme.mjs";

const model = {
  protocol: 22,
  herdrVersion: "0.9.1",
  selection: { workspaceId: "w1", tabId: "w1:t1", paneId: "w1:p1" },
  workspaceOrder: ["w1"],
  workspaces: { w1: { id: "w1", label: "API", agentStatus: "unknown", tabIds: ["w1:t1"] } },
  tabs: { "w1:t1": { id: "w1:t1", label: "Main", paneIds: ["w1:p1"] } },
  panes: { "w1:p1": { id: "w1:p1", label: "Build", agent: { kind: "pi", status: "unknown" }, cwd: "/repo", preview: "compiled" } },
};

test("renders typed RGB and ANSI palette tokens without guessing colors", () => {
  const theme = {
    palette: PALETTE_FIXTURE.themes.terminal,
  };
  const output = renderOverview({ model, theme }, 80);
  assert.ok(output.includes("\u001b[34mHerdr Overview"), "terminal accent is ANSI blue");
  assert.ok(output.includes("\u001b[37mAPI"), "terminal mauve is ANSI gray");

  const custom = renderOverview({
    model,
    theme: { palette: { ...PALETTE_FIXTURE.themes.terminal, accent: { kind: "rgb", hex: "#010203" } } },
  }, 80);
  assert.ok(custom.includes("\u001b[38;2;1;2;3mHerdr Overview"));
});

test("live pane output refreshes the open view without competing for the plugin state lock", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "herdr-overview-live-output-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const stateDir = path.join(root, "state");
  await mkdir(stateDir);
  const statePath = path.join(stateDir, "overview.json");
  await writeFile(statePath, JSON.stringify({ model, theme: { palette: PALETTE_FIXTURE.themes.terminal } }));
  const configPath = path.join(root, "config.toml");
  await writeFile(configPath, '[theme]\nname = "terminal"\nauto_switch = false\n');
  const input = new EventEmitter();
  input.isTTY = true;
  input.setRawMode = (enabled) => { input.isRaw = enabled; };
  input.resume = () => {};
  input.pause = () => {};
  const frames = [];
  let rendered;
  const firstFrame = new Promise((resolve) => { rendered = resolve; });
  const output = { columns: 100, rows: 24, isTTY: false, write: (text) => {
    frames.push(text);
    if (text.includes("Herdr Overview")) rendered();
  } };
  let onOutput;
  let subscribed;
  const ready = new Promise((resolve) => { subscribed = resolve; });
  const api = { async subscribe(_subscriptions, callback) {
    onOutput = callback;
    subscribed();
    return { close() {} };
  } };

  const session = runOverviewPane({ api, stateDir, configPath, input, output });
  try {
    await ready;
    await firstFrame;
    onOutput({ event: "pane.output_matched", data: { pane_id: "w1:p1", read: { text: "live excerpt" } } });
    assert.match(frames.at(-1), /live excerpt/);
    const saved = JSON.parse(await readFile(statePath, "utf8"));
    assert.equal(saved.model.panes["w1:p1"].preview, "compiled", "output redraw does not lock/rewrite plugin state");
  } finally {
    input.emit("end");
    await session;
  }
});

test("overlapping output subscriptions all close when the overview quits", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "herdr-overview-subscribe-race-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const stateDir = path.join(root, "state");
  await mkdir(stateDir);
  const statePath = path.join(stateDir, "overview.json");
  await writeFile(statePath, JSON.stringify({ model }));
  const configPath = path.join(root, "config.toml");
  await writeFile(configPath, '[theme]\nname = "terminal"\n');
  const input = new EventEmitter();
  input.isTTY = true;
  input.setRawMode = () => {};
  input.resume = () => {};
  input.pause = () => {};
  const output = Object.assign(new EventEmitter(), {
    columns: 100, rows: 24, isTTY: false, write: () => {},
  });
  const pending = [];
  const closed = [];
  const api = {
    async subscribe() {
      return await new Promise((resolve) => pending.push(resolve));
    },
  };
  const until = async (predicate) => {
    for (let attempt = 0; attempt < 100; attempt++) {
      if (predicate()) return;
      await new Promise((resolve) => setTimeout(resolve, 20));
    }
    throw new Error("overview subscription race did not reach the expected step");
  };
  const session = runOverviewPane({ api, stateDir, configPath, input, output });
  await until(() => pending.length >= 1);
  await writeFile(statePath, JSON.stringify({ model, generated_at: "later" }));
  await until(() => pending.length >= 2);
  for (const [index, resolve] of pending.entries()) resolve({ close: () => closed.push(index) });
  await until(() => input.listenerCount("data") > 0);
  input.emit("data", Buffer.from("q"));
  await session;
  assert.deepEqual(closed.sort(), [0, 1], "no subscription survives the closed overview process");
});

test("reopening reads current native output before showing a stale saved preview", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "herdr-overview-reopen-output-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const stateDir = path.join(root, "state");
  await mkdir(stateDir);
  const savedModel = structuredClone(model);
  savedModel.panes["w1:p1"].preview = "saved output before close";
  const statePath = path.join(stateDir, "overview.json");
  await writeFile(statePath, JSON.stringify({ model: savedModel }));
  const configPath = path.join(root, "config.toml");
  await writeFile(configPath, '[theme]\nname = "terminal"\nauto_switch = false\n');

  const input = new EventEmitter();
  input.isTTY = true;
  input.setRawMode = (enabled) => { input.isRaw = enabled; };
  input.resume = () => {};
  input.pause = () => {};
  const frames = [];
  const output = Object.assign(new EventEmitter(), {
    columns: 100, rows: 24, isTTY: true,
    write: (text) => { frames.push(text); },
  });
  let subscribed;
  const ready = new Promise((resolve) => { subscribed = resolve; });
  const reads = [];
  const api = {
    async readPane(paneId, options) {
      reads.push({ paneId, options });
      return "CLOSED_VIEW_NEW_OUTPUT_MARKER";
    },
    async subscribe() { subscribed(); return { close() {} }; },
  };
  const session = runOverviewPane({ api, stateDir, configPath, input, output });
  await ready;
  await new Promise((resolve) => setImmediate(resolve));
  try {
    assert.deepEqual(reads.map((read) => read.paneId), ["w1:p1"]);
    assert.deepEqual(reads[0].options, { lines: 12, source: "recent_unwrapped" });
    assert.match(frames.at(-1), /CLOSED_VIEW_NEW_OUTPUT_MARKER/);
    assert.doesNotMatch(frames.at(-1), /saved output before close/);
    assert.equal(JSON.parse(await readFile(statePath, "utf8")).model.panes["w1:p1"].preview, "saved output before close");
  } finally {
    input.emit("end");
    await session;
  }
});

test("a PTY resize switches Board and Mosaic at each open journey level", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "herdr-overview-resize-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const stateDir = path.join(root, "state");
  await mkdir(stateDir);
  await writeFile(path.join(stateDir, "overview.json"), JSON.stringify({ model }));
  const configPath = path.join(root, "config.toml");
  await writeFile(configPath, '[theme]\nname = "terminal"\nauto_switch = false\n');
  const input = new EventEmitter();
  input.isTTY = true;
  input.setRawMode = (enabled) => { input.isRaw = enabled; };
  input.resume = () => {};
  input.pause = () => {};
  const frames = [];
  const output = Object.assign(new EventEmitter(), {
    columns: 100, rows: 24, isTTY: true,
    write: (text) => { frames.push(text); },
  });
  let subscribed;
  const ready = new Promise((resolve) => { subscribed = resolve; });
  const api = { async subscribe() { subscribed(); return { close() {} }; } };
  const session = runOverviewPane({ api, stateDir, configPath, input, output });
  await ready;
  await new Promise((resolve) => setImmediate(resolve));
  try {
    assert.match(frames.at(-1), /· Mosaic/);
    output.columns = 48;
    output.emit("resize");
    assert.match(frames.at(-1), /· Board/);

    input.emit("data", Buffer.from("\r"));
    assert.match(frames.at(-1), /· Board · workspace/);
    output.columns = 100;
    output.emit("resize");
    assert.match(frames.at(-1), /· Mosaic · workspace/);

    input.emit("data", Buffer.from("\r"));
    assert.match(frames.at(-1), /· Mosaic · selected pane/);
    output.columns = 48;
    output.emit("resize");
    assert.match(frames.at(-1), /· Board · pane detail/);
  } finally {
    input.emit("end");
    await session;
  }
  const frameCount = frames.length;
  output.emit("resize");
  assert.equal(frames.length, frameCount, "closed panes do not redraw on resize");
});
