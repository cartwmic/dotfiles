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
  const output = { columns: 100, rows: 24, isTTY: false, write: (text) => { frames.push(text); } };
  let onOutput;
  let subscribed;
  const ready = new Promise((resolve) => { subscribed = resolve; });
  const api = { async subscribe(_subscriptions, callback) {
    onOutput = callback;
    subscribed();
    return { close() {} };
  } };

  const session = runOverviewPane({ api, stateDir, configPath, input, output });
  await ready;
  onOutput({ event: "pane.output_matched", data: { pane_id: "w1:p1", read: { text: "live excerpt" } } });
  assert.match(frames.at(-1), /live excerpt/);
  const saved = JSON.parse(await readFile(statePath, "utf8"));
  assert.equal(saved.model.panes["w1:p1"].preview, "compiled", "output redraw does not lock/rewrite plugin state");
  input.emit("end");
  await session;
});
