import test from "node:test";
import assert from "node:assert/strict";
import net from "node:net";
import { spawn } from "node:child_process";
import { mkdir, mkdtemp, readFile, writeFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { piSessionFile, readPiSessionFields } from "../src/pi-session-store.mjs";
import { evaluateDisplayNamePolicy } from "../src/display-name-policy.mjs";

test("public event CLI reads verified names/digests passively and rekeys only a unique live terminal", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "stable-subject-path-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const socketPath = path.join(root, "herdr.sock");
  const sessionId = "11111111-1111-4111-8111-111111111111";
  const env = { ...process.env, HOME: root, HERDR_SOCKET_PATH: socketPath,
    HERDR_PLUGIN_STATE_DIR: path.join(root, "state"), HERDR_CONFIG_PATH: path.join(root, "config.toml"),
    XDG_DATA_HOME: path.join(root, "data"), HERDR_OVERVIEW_PI_SESSIONS_DIR: path.join(root, "bindings"),
    PI_SESSION_SEARCH_DIGEST_DIR: path.join(root, "digests") };
  await writeFile(env.HERDR_CONFIG_PATH, '[theme]\nname = "nord"\nauto_switch = false\n');
  await mkdir(env.HERDR_OVERVIEW_PI_SESSIONS_DIR); await mkdir(env.PI_SESSION_SEARCH_DIGEST_DIR);
  const binding = { schemaVersion: 1, socketPath, terminalId: "term-one", paneId: "w:p1", sessionId,
    sessionName: "Synthetic stable subject", publisherPid: process.pid, generation: "fixture-one" };
  const saveBinding = () => writeFile(piSessionFile(socketPath, "term-one", env), JSON.stringify(binding));
  const saveDigest = (body) => writeFile(path.join(env.PI_SESSION_SEARCH_DIGEST_DIR, sessionId + ".json"), JSON.stringify({ schemaVersion: 1, body, generatedAt: "2026-10-01T00:00:00Z" }));
  await saveBinding(); await saveDigest("Synthetic digest one");
  const current = { protocol: 22, version: "0.9.1", workspaces: [{ workspace_id: "w", label: "Keep workspace" }],
    tabs: [{ tab_id: "w:t1", workspace_id: "w", label: "1" }],
    panes: [{ pane_id: "w:p1", workspace_id: "w", tab_id: "w:t1", terminal_id: "term-one", label: null, agent_session: null }], agents: [] };
  const calls = [];
  const server = net.createServer(socket => {
    let buffer = "";
    socket.on("data", chunk => {
      buffer += chunk;
      let newline;
      while ((newline = buffer.indexOf("\n")) >= 0) {
        const request = JSON.parse(buffer.slice(0, newline)); buffer = buffer.slice(newline + 1); calls.push(request);
        let result = { type: "ok" };
        if (request.method === "session.snapshot") result = { snapshot: current };
        else if (request.method === "pane.read") result = { read: { text: "Not a subject" } };
        else if (request.method === "pane.process_info") result = { process_info: null };
        else if (request.method === "pane.rename") current.panes.find(p => p.pane_id === request.params.pane_id).label = request.params.label;
        else if (request.method === "tab.rename") current.tabs.find(tab => tab.tab_id === request.params.tab_id).label = request.params.label;
        else assert.fail(`unexpected generation/open method ${request.method}`);
        socket.write(JSON.stringify({ id: request.id, result }) + "\n");
      }
    });
  });
  await new Promise(resolve => server.listen(socketPath, resolve));
  t.after(() => new Promise(resolve => server.close(resolve)));
  const run = async () => {
    const child = spawn(process.execPath, [fileURLToPath(new URL("../index.mjs", import.meta.url)), "event"], { env, stdio: ["ignore", "pipe", "pipe"] });
    let error = ""; child.stderr.on("data", chunk => { error += chunk; });
    assert.equal(await new Promise(resolve => child.on("close", resolve)), 0, error);
    return JSON.parse(await readFile(path.join(env.HERDR_PLUGIN_STATE_DIR, "overview.json"), "utf8"));
  };
  // Exercise typed pane and agent identities through the public event entry.
  const nativeId = { source: "herdr:pi", agent: "pi", kind: "id", value: sessionId };
  current.panes[0].agent_session = nativeId;
  current.agents = [{ pane_id: "w:p1", agent_session: { ...nativeId } }];
  const renames = () => calls.filter(c => c.method.endsWith(".rename"));
  let state = await run();
  assert.equal(renames().length, 2);
  assert.equal(state.model.panes["w:p1"].sessionName, binding.sessionName);
  assert.equal(state.model.panes["w:p1"].agent.recognized, false);
  assert.equal(state.model.panes["w:p1"].agent.status, "unknown");
  for (const invalid of [false, "", sessionId, {}, { ...nativeId, agent: "codex" },
    { ...nativeId, kind: "path" }, { ...nativeId, value: "22222222-2222-4222-8222-222222222222" }]) {
    current.agents[0].agent_session = invalid;
    const rejected = await run();
    assert.equal(rejected.model.panes["w:p1"].piSession, null);
    assert.equal(rejected.model.panes["w:p1"].digest.body, null);
  }
  current.agents[0].agent_session = { ...nativeId };
  await saveDigest("Changed digest body");
  const recapRoot = path.join(root, "data", "session-recap");
  await mkdir(path.join(recapRoot, "records", "2026-10-01"), { recursive: true });
  const record = { record_id: "fixture-recap", source_kind: "pi-session", source_id: sessionId, pane_id: "w:p1", workspace_id: "w", status: "published", summary: "Changed recap body", created_at: "2026-10-01T00:00:00Z", published_at: "2026-10-01T00:00:00Z" };
  await writeFile(path.join(recapRoot, "records", "2026-10-01", "fixture-recap.json"), JSON.stringify(record));
  await writeFile(path.join(recapRoot, "latest.json"), JSON.stringify({ sources: [{ source_kind: "pi-session", source_id: sessionId, latest_success_id: record.record_id, last_attempt_id: record.record_id }] }));
  state = await run(); await run();
  assert.equal(renames().length, 2, "body/publication/redraw cause no native writes");
  assert.equal(state.model.panes["w:p1"].digest.body, "Changed digest body");
  assert.equal(state.model.panes["w:p1"].recap.latest.summary, record.summary);
  await writeFile(path.join(recapRoot, "records", "2026-10-01", "fixture-failed.json"), JSON.stringify({ ...record, record_id: "fixture-failed", status: "failed", error: "Synthetic failure", summary: undefined }));
  await writeFile(path.join(recapRoot, "latest.json"), JSON.stringify({ sources: [{ source_kind: "pi-session", source_id: sessionId, latest_success_id: record.record_id, last_attempt_id: "fixture-failed" }] }));
  state = await run();
  assert.equal(state.model.panes["w:p1"].recap.latest.summary, record.summary);
  assert.equal(state.model.panes["w:p1"].recap.lastAttempt.status, "failed");
  assert.equal(renames().length, 2);
  binding.sessionName = "Changed stable subject"; await saveBinding(); await run();
  assert.equal(renames().length, 4, "real subject changes write");
  current.panes.push({ pane_id: "w:p2", workspace_id: "w", tab_id: "w:t1", terminal_id: "term-two", label: null });
  state = await run();
  assert.equal(state.model.tabs["w:t1"].fullTitle, "Changed stable subject + 1 more");
  assert.equal(renames().length, 5, "unknown live sibling counts toward tab title");
  current.panes[0].pane_id = "w:p3";
  current.agents[0].pane_id = "w:p3";
  state = await run();
  assert.equal(state.model.panes["w:p3"].piSession.sessionId, sessionId);
  assert.equal(state.model.panes["w:p3"].recap.latest.summary, record.summary);
  assert.equal(state.model.panes["w:p3"].recap.lastAttempt.status, "failed");
  assert.equal(state.displayNameOwnership["pane:w:p1"], undefined);
  assert.equal(state.displayNameOwnership["pane:w:p3"].mode, "automatic");
  assert.equal(renames().length, 5, "rekey retains stable ownership without churn");
  current.panes[0].label = "Manual pane"; await run();
  assert.equal(renames().at(-1).params.label, "Manual pane + 1 more");
  current.tabs[0].label = "Manual tab"; binding.sessionName = "Another subject"; await saveBinding();
  state = await run(); assert.equal(renames().length, 6);
  assert.equal(state.model.tabs["w:t1"].fullTitle, "Manual tab");
  current.panes[0].agent_session = null;
  current.agents = [];
  current.panes.push({ ...current.panes[0], pane_id: "w:p4" });
  state = await run();
  assert.equal(state.model.panes["w:p3"].piSession, null);
  assert.equal(state.model.panes["w:p4"].digest.reason, "unmatched");
  assert.equal(state.model.panes["w:p3"].recap.latest, null);
  assert.equal(state.model.panes["w:p4"].recap.latest, null);
 });

test("full subjects survive native bounds and generic fallbacks stay honest", () => {
  const full = "Synthetic full subject ".repeat(12).trim();
  const snapshot = { panes: [{ pane_id: "p", tab_id: "t", label: null }], tabs: [{ tab_id: "t", workspace_id: "w", label: "1" }], agents: [] };
  let result = evaluateDisplayNamePolicy(snapshot, { supplied: { piSessionsByPaneId: { p: { sessionName: full } } } });
  assert.equal(result.paneSubjects.p, full); assert.equal(result.tabTitles.t, full);
  assert.equal(result.rename[0].label.length, 72); assert.equal(result.rename[1].label.length, 160);
  snapshot.panes[0].terminal_title_stripped = "π - Synthetic fallback - /repo";
  result = evaluateDisplayNamePolicy(snapshot);
  assert.equal(result.paneSubjects.p, "Synthetic fallback");
  delete snapshot.panes[0].terminal_title_stripped;
  snapshot.panes[0].agent = "pi";
  assert.equal(evaluateDisplayNamePolicy(snapshot).paneSubjects.p, null);
 });


test("reader requires every present native pane/agent identity to match the exact Pi id", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "native-pi-id-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const env = { HOME: root, HERDR_OVERVIEW_PI_SESSIONS_DIR: root };
  const socketPath = "/synthetic/native.sock";
  const sessionId = "11111111-1111-4111-8111-111111111111";
  await writeFile(piSessionFile(socketPath, "terminal", env), JSON.stringify({ schemaVersion: 1,
    socketPath, terminalId: "terminal", paneId: "old", sessionId, sessionName: null,
    publisherPid: process.pid, generation: "current" }));
  const native = { source: "herdr:pi", agent: "pi", kind: "id", value: sessionId };
  const snapshot = { protocol: 22, panes: [{ pane_id: "new", terminal_id: "terminal", agent_session: native }],
    agents: [{ pane_id: "new", agent_session: native }] };
  const read = () => readPiSessionFields(snapshot, { socketPath, env }).piSessionsByPaneId.new;
  assert.equal(read().sessionId, sessionId);
  for (const field of [snapshot.panes[0], snapshot.agents[0]]) {
    for (const invalid of [false, "", sessionId, {}, { ...native, agent: "codex" },
      { ...native, kind: "path" }, { ...native, value: "22222222-2222-4222-8222-222222222222" }]) {
      field.agent_session = invalid;
      assert.equal(read(), undefined);
    }
    field.agent_session = native;
  }
  assert.equal(read().sessionId, sessionId);
});
