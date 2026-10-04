import test from "node:test";
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { mkdir, mkdtemp, readFile, rm, unlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { reconcileOverview } from "../src/coordinator.mjs";
import { readAllRecapRecords } from "../src/recap-store.mjs";
import { normalizeSnapshot } from "../src/model.mjs";
import { runOverviewPane } from "../src/pane.mjs";
import { snapshot as popupSnapshot } from "./popup-fixture.mjs";

const wait = async (predicate) => {
  for (let n = 0; n < 400; n++) { if (await predicate()) return; await new Promise((r) => setTimeout(r, 5)); }
  throw new Error("wait timeout");
};
const hex = (n) => n.toString(16).padStart(32, "0");

async function runtime(t) {
  const root = await mkdtemp(path.join(os.tmpdir(), "overview-perf-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const dataRoot = path.join(root, "session-recap");
  const day = path.join(dataRoot, "records", "2026-10-04");
  await mkdir(day, { recursive: true });
  const stateDir = path.join(root, "state");
  const configPath = path.join(root, "config.toml");
  await writeFile(configPath, '[theme]\nname="catppuccin"\n');
  const writeRecord = (record) => writeFile(path.join(day, `${record.record_id}.json`), JSON.stringify(record));
  return { root, dataRoot, day, stateDir, configPath, writeRecord };
}

function piRecord(id, publishedAt, { workspace = "ws-a", pane = "pane-a", session = "11111111-1111-4111-8111-111111111111" } = {}) {
  return {
    schema_version: 2, record_id: id, status: "published", source_kind: "pi", source_id: `history-${session}`,
    created_at: publishedAt, published_at: publishedAt, summary: `Work ${id.slice(-2)}`,
    metadata: { pi: { sessionId: session, coverage: { blob: "x".repeat(4096) } } },
    annotations: { herdr: { pane_id: pane, workspace_id: workspace } },
  };
}

const api = {
  socketPath: "/tmp/overview-perf.sock",
  async snapshot() {
    return {
      protocol: 22, focused_workspace_id: "ws-a", focused_tab_id: "tab-a", focused_pane_id: "pane-a",
      workspaces: [{ workspace_id: "ws-a", number: 1, label: "a", focused: true, active_tab_id: "tab-a", agent_status: "idle" }],
      tabs: [{ tab_id: "tab-a", workspace_id: "ws-a", number: 1, label: "a", focused: true, agent_status: "idle" }],
      panes: [{ pane_id: "pane-a", tab_id: "tab-a", workspace_id: "ws-a", terminal_id: "term-a", focused: true, agent: "pi", agent_status: "idle" }],
      agents: [{ pane_id: "pane-a", agent: "pi" }], layouts: [],
    };
  },
  async readPane() { return ""; },
  async processInfo() { return null; },
  async renamePane() {}, async renameTab() {},
};

test("group generation runs outside the state lock and keeps a deadline extended meanwhile", async (t) => {
  const rt = await runtime(t);
  const first = piRecord(hex(1), "2026-10-04T00:00:00.000Z");
  await rt.writeRecord(first);
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  let groups = 0;
  const recapRunner = async (args, input) => {
    if (args[0] === "config") return "enabled";
    assert.equal(args[0], "create");
    groups += 1;
    if (groups === 1) await gate;
    const id = hex(100 + groups);
    const kind = args[args.indexOf("--source-kind") + 1];
    const source = args[args.indexOf("--source-id") + 1];
    await rt.writeRecord({ schema_version: 2, record_id: id, status: "published", source_kind: kind, source_id: source,
      kind: "group", created_at: new Date().toISOString(), published_at: new Date().toISOString(),
      summary: `group of ${JSON.parse(input).members.length}` });
    return id;
  };
  const options = { api, stateDir: rt.stateDir, dataRoot: rt.dataRoot, configPath: rt.configPath, recapRunner,
    scheduleWakeup: () => {}, env: {} };
  const deadline = "2026-10-04T00:00:30.000Z";
  const grouping = reconcileOverview({ ...options, coordinatorWake: true, coordinatorNow: () => Date.parse(deadline) });
  await wait(() => groups === 1);

  // While the model call is blocked, an event reconcile finishes and a newer
  // publication extends the same workspace's quiet window.
  const second = piRecord(hex(2), "2026-10-04T00:00:10.000Z", { pane: "pane-a" });
  await rt.writeRecord(second);
  const eventState = await reconcileOverview({ ...options, event: { event: "pane.agent_status_changed", data: { pane_id: "pane-a" } } });
  assert.equal(eventState.model.panes["pane-a"].recap.latest.record_id, second.record_id);
  const extended = await reconcileOverview({ ...options, coordinatorWake: true, coordinatorNow: () => Date.parse(deadline) - 1 });
  assert.equal(extended.recapCoordinator.workspaceDeadlines["ws-a"], "2026-10-04T00:00:40.000Z");

  release();
  const state = await grouping;
  assert.equal(state.recapCoordinator.workspaceDeadlines["ws-a"], "2026-10-04T00:00:40.000Z", "the later window still needs its own group");
  assert.equal(groups, 2, "one workspace group plus one session group");
  assert.match(state.model.workspaces["ws-a"].recap.latest.summary, /^group of 1$/);
  assert.equal(JSON.stringify(state).includes('"coverage"'), false, "saved state omits Pi coverage");
});

test("record cache picks up rewritten and removed records and leaves files untouched", async (t) => {
  const rt = await runtime(t);
  const record = piRecord(hex(3), "2026-10-04T00:00:00.000Z");
  await rt.writeRecord(record);
  let [read] = await readAllRecapRecords(rt.dataRoot);
  assert.equal(read.summary, record.summary);
  assert.equal(read.metadata.pi.coverage, undefined);
  assert.equal(read.metadata.pi.sessionId, record.metadata.pi.sessionId);
  assert.deepEqual(JSON.parse(await readFile(path.join(rt.day, `${record.record_id}.json`), "utf8")), record);

  await rt.writeRecord({ ...record, summary: "Rewritten summary with a different length" });
  [read] = await readAllRecapRecords(rt.dataRoot);
  assert.equal(read.summary, "Rewritten summary with a different length");
  await unlink(path.join(rt.day, `${record.record_id}.json`));
  assert.deepEqual(await readAllRecapRecords(rt.dataRoot), []);
});

test("popup coalesces saved-state refreshes and handles keys while one runs", async (t) => {
  const rt = await runtime(t);
  const native = popupSnapshot();
  await mkdir(rt.stateDir, { recursive: true });
  await writeFile(path.join(rt.stateDir, "overview.json"), JSON.stringify({ model: normalizeSnapshot(native) }));
  const input = new EventEmitter();
  Object.assign(input, { isTTY: true, isRaw: false, setRawMode(v) { this.isRaw = v; }, resume() {}, pause() {} });
  const output = new EventEmitter(); const frames = [];
  Object.assign(output, { columns: 100, rows: 30, isTTY: false, write(text) { frames.push(text); } });
  let snapshots = 0; let slow = false;
  const slowApi = { async snapshot() { snapshots += 1; if (slow) await new Promise((r) => setTimeout(r, 150)); return native; } };
  const running = runOverviewPane({ api: slowApi, stateDir: rt.stateDir, dataRoot: rt.dataRoot, configPath: rt.configPath, input, output });
  t.after(async () => { input.emit("data", Buffer.from("q")); await running; });
  await wait(() => input.listenerCount("data") > 0);
  const before = snapshots; slow = true;
  for (let n = 0; n < 8; n++) {
    await writeFile(path.join(rt.stateDir, "overview.json"), JSON.stringify({ model: normalizeSnapshot(native), n }));
    await new Promise((r) => setTimeout(r, 10));
  }
  await wait(() => snapshots > before);
  assert.equal(frames.at(-1).includes("› Tab 2"), false);
  const pressed = Date.now();
  input.emit("data", Buffer.from("]"));
  // The selection moves without waiting for the slow (150 ms) refreshes.
  await wait(() => frames.at(-1).includes("› Tab 2"));
  assert.ok(Date.now() - pressed < 120, `key waited ${Date.now() - pressed} ms behind refreshes`);
  await new Promise((r) => setTimeout(r, 1500));
  assert.ok(snapshots - before <= 3, `eight saved-state writes coalesce (${snapshots - before} snapshots)`);
});
