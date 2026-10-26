import test from "node:test";
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { chmod, mkdir, mkdtemp, readFile, readdir, rm, stat, truncate, unlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { reconcileOverview } from "../src/coordinator.mjs";

const run = promisify(execFile);
const storeUrl = new URL("../src/recap-store.mjs", import.meta.url).href;
const hex = (n) => n.toString(16).padStart(32, "0");

// A Herdr hook is a fresh node process, so each call here is one.
async function scanInNewProcess(root, indexPath) {
  const script = `
    import { openRecapIndex, readAllRecapRecords, saveRecapIndex } from ${JSON.stringify(storeUrl)};
    await openRecapIndex(${JSON.stringify(root)}, ${JSON.stringify(indexPath)});
    const records = await readAllRecapRecords(${JSON.stringify(root)});
    await saveRecapIndex();
    console.log(JSON.stringify(records.map((r) => [r.record_id, r.summary, r.metadata?.pi?.coverage === undefined]).sort()));`;
  const { stdout } = await run(process.execPath, ["--input-type=module", "-e", script]);
  return JSON.parse(stdout);
}

async function fixture(t, count = 3) {
  const base = await mkdtemp(path.join(os.tmpdir(), "overview-index-"));
  t.after(() => rm(base, { recursive: true, force: true }));
  const root = path.join(base, "session-recap");
  const day = path.join(root, "records", "2026-10-04");
  await mkdir(day, { recursive: true });
  const files = [];
  for (let n = 1; n <= count; n++) {
    const record = {
      schema_version: 2, record_id: hex(n), status: "published", source_kind: "pi", source_id: `history-${n}`,
      created_at: "2026-10-04T00:00:00Z", published_at: "2026-10-04T00:00:00Z", summary: `Work ${n}`,
      metadata: { pi: { sessionId: `session-${n}`, coverage: { blob: "x".repeat(8192) } } },
    };
    const file = path.join(day, `${record.record_id}.json`);
    await writeFile(file, JSON.stringify(record));
    files.push(file);
  }
  return { base, root, day, files, indexPath: path.join(base, "state", "recap-index.json") };
}

test("a new process reuses the saved index: unchanged files are not parsed again", async (t) => {
  if (process.getuid?.() === 0) return t.skip("root can read a mode-000 file, so reuse cannot be proven");
  const f = await fixture(t);
  const first = await scanInNewProcess(f.root, f.indexPath);
  assert.equal(first.length, 3);
  assert.ok(first.every(([, , noCoverage]) => noCoverage), "projection omits Pi coverage");

  const index = await readFile(f.indexPath, "utf8");
  assert.equal(index.includes("xxxxxxxx"), false, "the index never carries coverage");
  assert.equal((await stat(f.indexPath)).mode & 0o777, 0o600);

  // An unreadable file (same mtime, size and inode) breaks any re-parse. Only the index can answer.
  await chmod(f.files[0], 0o000);
  await assert.rejects(readFile(f.files[0]), { code: "EACCES" });
  assert.deepEqual(await scanInNewProcess(f.root, f.indexPath), first);
});

test("a new process parses only added and rewritten files and forgets removed ones", async (t) => {
  const f = await fixture(t);
  await scanInNewProcess(f.root, f.indexPath);

  const changed = JSON.parse(await readFile(f.files[1], "utf8"));
  await writeFile(f.files[1], JSON.stringify({ ...changed, summary: "Rewritten with a different length" }));
  await unlink(f.files[2]);
  await writeFile(path.join(f.day, `${hex(9)}.json`), JSON.stringify({ ...changed, record_id: hex(9), summary: "Added" }));

  const second = await scanInNewProcess(f.root, f.indexPath);
  assert.deepEqual(second.map(([id, summary]) => [id, summary]), [
    [hex(1), "Work 1"], [hex(2), "Rewritten with a different length"], [hex(9), "Added"],
  ]);
  assert.deepEqual(await scanInNewProcess(f.root, f.indexPath), second, "and the saved index matches");
});

test("a corrupt, foreign or outdated index costs a re-parse, not a wrong answer", async (t) => {
  const f = await fixture(t, 2);
  const expected = await scanInNewProcess(f.root, f.indexPath);
  const saved = JSON.parse(await readFile(f.indexPath, "utf8"));
  for (const bad of [
    "not json",
    JSON.stringify({ ...saved, version: 0 }),
    JSON.stringify({ ...saved, root: "/somewhere/else", entries: saved.entries.map(([file, key]) => [file, key, null]) }),
  ]) {
    await writeFile(f.indexPath, bad);
    assert.deepEqual(await scanInNewProcess(f.root, f.indexPath), expected);
  }
  await truncate(f.indexPath, 5);
  assert.deepEqual(await scanInNewProcess(f.root, f.indexPath), expected);
});

test("a file that could not be read is retried by the next process, not remembered as missing", async (t) => {
  if (process.getuid?.() === 0) return t.skip("root can read a mode-000 file");
  const f = await fixture(t, 2);
  await chmod(f.files[0], 0o000);
  assert.equal((await scanInNewProcess(f.root, f.indexPath)).length, 1);
  await chmod(f.files[0], 0o644);
  assert.equal((await scanInNewProcess(f.root, f.indexPath)).length, 2, "same mtime, size and inode, now readable");
});

test("index entries outside the root or with a bad shape are ignored", async (t) => {
  const f = await fixture(t, 1);
  await scanInNewProcess(f.root, f.indexPath);
  const saved = JSON.parse(await readFile(f.indexPath, "utf8"));
  const [file, key] = saved.entries[0];
  saved.entries = [
    "junk", [], [42, key, { record_id: "x" }], [file, 7, { record_id: "x" }], [file, key, null], [file, key, "text"],
    ["/elsewhere/records/2026-10-04/" + hex(5) + ".json", key, { record_id: hex(5), summary: "foreign" }],
  ];
  await writeFile(f.indexPath, JSON.stringify(saved));
  assert.deepEqual((await scanInNewProcess(f.root, f.indexPath)).map(([id, summary]) => [id, summary]), [[hex(1), "Work 1"]]);
});

test("an unwritable index location never fails the scan", async (t) => {
  const f = await fixture(t, 1);
  await writeFile(path.join(f.base, "state"), "a file where the state directory should be");
  assert.equal((await scanInNewProcess(f.root, f.indexPath)).length, 1);
});

test("reconcileOverview saves a coverage-free index beside its state file", async (t) => {
  const f = await fixture(t, 2);
  const stateDir = path.join(f.base, "state");
  await rm(stateDir, { recursive: true, force: true });
  const configPath = path.join(f.base, "config.toml");
  await writeFile(configPath, '[theme]\nname="catppuccin"\n');
  const api = {
    socketPath: "/tmp/overview-index.sock",
    async snapshot() {
      return {
        protocol: 22, focused_workspace_id: "ws-a", focused_tab_id: "tab-a", focused_pane_id: "pane-a",
        workspaces: [{ workspace_id: "ws-a", number: 1, label: "a", focused: true, active_tab_id: "tab-a", agent_status: "idle" }],
        tabs: [{ tab_id: "tab-a", workspace_id: "ws-a", number: 1, label: "a", focused: true, agent_status: "idle" }],
        panes: [{ pane_id: "pane-a", tab_id: "tab-a", workspace_id: "ws-a", terminal_id: "term-a", focused: true, agent: "pi", agent_status: "idle" }],
        agents: [{ pane_id: "pane-a", agent: "pi" }], layouts: [],
      };
    },
    async readPane() { return ""; }, async processInfo() { return null; }, async renamePane() {}, async renameTab() {},
  };
  await reconcileOverview({ api, stateDir, dataRoot: f.root, configPath });
  const index = JSON.parse(await readFile(path.join(stateDir, "recap-index.json"), "utf8"));
  assert.equal(index.entries.length, 2);
  assert.equal(JSON.stringify(index).includes("xxxxxxxx"), false);
});

test("two hooks started together with no index both finish and leave one valid index", async (t) => {
  const f = await fixture(t, 40);
  const stateDir = path.join(f.base, "state");
  await rm(stateDir, { recursive: true, force: true });
  const configPath = path.join(f.base, "config.toml");
  await writeFile(configPath, '[theme]\nname="catppuccin"\n');
  const coordinatorUrl = new URL("../src/coordinator.mjs", import.meta.url).href;
  const script = `
    import { reconcileOverview } from ${JSON.stringify(coordinatorUrl)};
    const api = {
      socketPath: "/tmp/overview-index.sock",
      async snapshot() {
        return {
          protocol: 22, focused_workspace_id: "ws-a", focused_tab_id: "tab-a", focused_pane_id: "pane-a",
          workspaces: [{ workspace_id: "ws-a", number: 1, label: "a", focused: true, active_tab_id: "tab-a", agent_status: "idle" }],
          tabs: [{ tab_id: "tab-a", workspace_id: "ws-a", number: 1, label: "a", focused: true, agent_status: "idle" }],
          panes: [{ pane_id: "pane-a", tab_id: "tab-a", workspace_id: "ws-a", terminal_id: "term-a", focused: true, agent: "pi", agent_status: "idle" }],
          agents: [{ pane_id: "pane-a", agent: "pi" }], layouts: [],
        };
      },
      async readPane() { return ""; }, async processInfo() { return null; }, async renamePane() {}, async renameTab() {},
    };
    await reconcileOverview({ api, stateDir: ${JSON.stringify(stateDir)}, dataRoot: ${JSON.stringify(f.root)}, configPath: ${JSON.stringify(configPath)} });`;
  const hook = () => run(process.execPath, ["--input-type=module", "-e", script]);
  await Promise.all([hook(), hook(), hook()]);
  const index = JSON.parse(await readFile(path.join(stateDir, "recap-index.json"), "utf8"));
  assert.equal(index.entries.length, 40);
  const leftovers = (await readdir(stateDir)).filter((name) => name.endsWith(".tmp") || name.startsWith("."));
  assert.deepEqual(leftovers, []);
  assert.equal(JSON.parse(await readFile(path.join(stateDir, "overview.json"), "utf8")).schema_version, 1);
});
