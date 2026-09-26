import test from "node:test";
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import net from "node:net";
import { chmod, mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { HerdrApi } from "../src/herdr-api.mjs";
import { normalizeSnapshot } from "../src/model.mjs";
import { runOverviewPane } from "../src/pane.mjs";
import { readTheme } from "../src/theme.mjs";

const NOW = Date.now();

function makeScenario() {
  const workspaces = [
    { id: "ws-1", label: "API", tabs: [
      { id: "ws-1:t1", label: "Build", panes: [
        { id: "ws-1:p1", label: "Pi task", agent: "pi", status: "working", preview: "latest API output" },
        { id: "ws-1:p2", label: "Shell", preview: "shell output" },
      ] },
      { id: "ws-1:t2", label: "Review", panes: [
        { id: "ws-1:p3", label: "Unknown agent", agent: null, recognized: false, status: "unknown", preview: "unclassified output" },
      ] },
    ] },
    { id: "ws-2", label: "Web", tabs: [
      { id: "ws-2:t1", label: "Frontend", panes: [
        { id: "ws-2:p4", label: "Codex", agent: "codex", status: "blocked", preview: "approval requested" },
        { id: "ws-2:p5", label: "Pi docs", agent: "pi", status: "working", preview: "documentation output" },
      ] },
      { id: "ws-2:t2", label: "Checks", panes: [
        { id: "ws-2:p6", label: "Test shell", preview: "tests finished" },
      ] },
    ] },
    { id: "ws-3", label: "Infra", tabs: [
      { id: "ws-3:t1", label: "Ops", panes: [
        { id: "ws-3:p7", label: "Deploy shell", preview: "terraform plan output" },
      ] },
      { id: "ws-3:t2", label: "Agent", panes: [
        { id: "ws-3:p8", label: "Completed Pi", agent: "pi", status: "done", preview: "deploy command completed" },
      ] },
    ] },
  ];
  const snapshot = {
    protocol: 22,
    version: "0.9.1",
    focused_workspace_id: "ws-1",
    focused_tab_id: "ws-1:t1",
    focused_pane_id: "ws-1:p1",
    workspaces: workspaces.map((workspace, index) => ({
      workspace_id: workspace.id,
      number: index + 1,
      label: workspace.label,
      focused: index === 0,
      active_tab_id: workspace.tabs[0].id,
      agent_status: "unknown",
    })),
    tabs: workspaces.flatMap((workspace) => workspace.tabs.map((tab, index) => ({
      tab_id: tab.id,
      workspace_id: workspace.id,
      number: index + 1,
      label: tab.label,
      focused: tab.id === "ws-1:t1",
      agent_status: "unknown",
    }))),
    panes: workspaces.flatMap((workspace) => workspace.tabs.flatMap((tab) => tab.panes.map((pane) => ({
      pane_id: pane.id,
      workspace_id: workspace.id,
      tab_id: tab.id,
      terminal_id: `term-${pane.id}`,
      focused: pane.id === "ws-1:p1",
      agent_status: pane.status ?? "unknown",
      revision: 1,
      label: pane.label,
      title: `${pane.label} title`,
      terminal_title_stripped: `${pane.label} terminal`,
      cwd: `/work/${workspace.id}`,
      agent: pane.agent,
      ...(pane.agent === "pi" ? { agent_session: { source: "herdr:pi", agent: "pi", kind: "id", value: pane.id } } : {}),
    })))),
    agents: workspaces.flatMap((workspace) => workspace.tabs.flatMap((tab) => tab.panes
      .filter((pane) => pane.agent || pane.recognized === false)
      .map((pane) => ({
        pane_id: pane.id,
        agent: pane.agent,
        display_agent: pane.agent === "pi" ? "Pi" : pane.agent === "codex" ? "Codex" : null,
        agent_status: pane.status ?? "unknown",
        ...(pane.agent === "pi" ? { agent_session: { agent: "pi", kind: "id", value: pane.id } } : {}),
      })))),
  };
  const panes = workspaces.flatMap((workspace) => workspace.tabs.flatMap((tab) => tab.panes));
  const outputByPaneId = Object.fromEntries(panes.map((pane) => [pane.id, pane.preview]));
  const processByPaneId = Object.fromEntries(panes.map((pane) => [pane.id, {
    foreground_processes: [{ name: pane.agent ?? "zsh" }],
  }]));
  const promptsByPaneId = {
    "ws-1:p1": { text: "Finish the API migration", working: true, captured_at: new Date(NOW - 60_000).toISOString() },
    "ws-2:p5": { text: "Document the frontend endpoint", working: true, captured_at: new Date(NOW - 30_000).toISOString() },
  };
  const piRecapsByPaneId = {
    "ws-1:p1": {
      latest: { record_id: "published-1", status: "published", summary: "Updated the API and added validation.", published_at: new Date(NOW - 120_000).toISOString() },
      lastAttempt: { record_id: "published-1", status: "published" },
    },
    "ws-2:p5": {
      latest: null,
      lastAttempt: { record_id: "failed-1", status: "failed", created_at: new Date(NOW - 180_000).toISOString(), failure: { message: "scripted backend unavailable" } },
    },
    "ws-3:p8": { latest: null, lastAttempt: null },
  };
  const model = normalizeSnapshot(snapshot, { promptsByPaneId, piRecapsByPaneId }, { outputByPaneId, processByPaneId });
  return { snapshot, workspaces, model };
}

class TestInput extends EventEmitter {
  isTTY = true;
  isRaw = false;
  setRawMode(value) { this.isRaw = value; }
  resume() {}
  pause() {}
  press(key) {
    const bytes = key === "enter" ? "\r" : key === "escape" ? "\u001b" : key;
    this.emit("data", Buffer.from(bytes));
  }
}

class TestOutput {
  isTTY = true;
  columns;
  rows;
  frames = [];
  pending = "";
  constructor(columns, rows) { this.columns = columns; this.rows = rows; }
  write(value) {
    if (value.includes("\u001b[2J")) { this.pending = ""; return true; }
    this.pending += value;
    if (this.pending.endsWith("\n")) {
      this.frames.push(this.pending);
      this.pending = "";
    }
    return true;
  }
  latest() { return this.frames.at(-1)?.replace(/\u001b\[[0-?]*[ -/]*[@-~]/g, "") ?? ""; }
}

async function waitFor(predicate, message) {
  const deadline = Date.now() + 3000;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  throw new Error(message);
}

async function scriptedServer(t, snapshot) {
  const root = await mkdtemp(path.join(os.tmpdir(), "herdr-presenter-socket-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const socketPath = path.join(root, "herdr.sock");
  const calls = [];
  const peers = new Set();
  const server = net.createServer((socket) => {
    peers.add(socket);
    socket.once("close", () => peers.delete(socket));
    let buffer = "";
    socket.on("data", (chunk) => {
      buffer += chunk.toString("utf8");
      let newline;
      while ((newline = buffer.indexOf("\n")) >= 0) {
        const request = JSON.parse(buffer.slice(0, newline));
        buffer = buffer.slice(newline + 1);
        calls.push(request);
        const result = request.method === "session.snapshot"
          ? { type: "session_snapshot", snapshot }
          : request.method === "events.subscribe"
            ? { type: "subscription_started" }
            : { type: "ok" };
        socket.write(`${JSON.stringify({ id: request.id, result })}\n`);
      }
    });
  });
  await new Promise((resolve, reject) => server.listen(socketPath, (error) => error ? reject(error) : resolve()));
  t.after(() => new Promise((resolve) => {
    for (const socket of peers) socket.destroy();
    server.close(resolve);
  }));
  return { socketPath, calls };
}

async function startPresenter({ t, columns, rows, scenario, stateDir, configPath, dataRoot, recapBin, calls }) {
  const input = new TestInput();
  const output = new TestOutput(columns, rows);
  const api = new HerdrApi({ socketPath: scenario.socketPath });
  const promise = runOverviewPane({
    api,
    stateDir,
    configPath,
    dataRoot,
    input,
    output,
    env: { ...process.env, SESSION_RECAP_BIN: recapBin },
  });
  t.after(async () => {
    if (input.listenerCount("data")) input.press("q");
    await promise;
  });
  await waitFor(() => input.listenerCount("data") === 1 && calls.some((call) => call.method === "events.subscribe"), "presenter did not start its input loop and native output subscription");
  return {
    input,
    output,
    promise,
    async press(key) {
      const frames = output.frames.length;
      input.press(key);
      await waitFor(() => output.frames.length > frames, `key ${JSON.stringify(key)} did not redraw the presenter`);
      return output.latest();
    },
  };
}

async function fixtureFiles(t, model) {
  const root = await mkdtemp(path.join(os.tmpdir(), "herdr-presenter-path-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const stateDir = path.join(root, "state");
  const dataRoot = path.join(root, "recaps");
  await mkdir(stateDir, { recursive: true });
  await mkdir(dataRoot, { recursive: true });
  const configPath = path.join(root, "config.toml");
  await writeFile(configPath, '[ui]\nmobile_width_threshold = 64\n[theme]\nname = "nord"\nauto_switch = false\n');
  const theme = await readTheme(configPath);
  await writeFile(path.join(stateDir, "overview.json"), `${JSON.stringify({ schema_version: 1, model, theme, displayNameOwnership: {} })}\n`);
  const recapMarker = path.join(root, "recap-called");
  const recapBin = path.join(root, "session-recap");
  await writeFile(recapBin, `#!/bin/sh\nprintf called >> '${recapMarker}'\nexit 97\n`);
  await chmod(recapBin, 0o755);
  return { root, stateDir, dataRoot, configPath, recapBin, recapMarker };
}

async function driveEveryNativePane({ t, width, rows, defs, model, files, socket, calls }) {
  const presenter = await startPresenter({ t, columns: width, rows, scenario: socket, ...files, calls });
  const expectedPresenter = width <= 64 ? "Board" : "Mosaic";
  assert.match(presenter.output.latest(), new RegExp(`· ${expectedPresenter}`));
  await presenter.press("r");
  if (expectedPresenter === "Mosaic") {
    for (const workspace of defs) assert.ok(presenter.output.latest().includes(workspace.label), `initial Mosaic omitted ${workspace.label}`);
    for (const paneId of model.paneOrder) assert.ok(presenter.output.latest().includes(paneId), `initial Mosaic omitted ${paneId}`);
  } else {
    for (const workspace of defs) assert.ok(presenter.output.latest().includes(workspace.label), `Board summary omitted ${workspace.label}`);
  }

  const focused = [];
  for (const [workspaceIndex, workspace] of defs.entries()) {
    if (workspaceIndex > 0) {
      await presenter.press("escape");
      const overview = await presenter.press("escape");
      assert.match(overview, /· (?:Board|Mosaic)/);
      const selectedWorkspace = await presenter.press("j");
      assert.ok(selectedWorkspace.includes(workspace.label), `could not select workspace ${workspace.label}`);
      await presenter.press("enter");
    } else {
      await presenter.press("enter");
    }

    for (const [tabIndex, tab] of workspace.tabs.entries()) {
      if (tabIndex > 0) {
        const tabFrame = await presenter.press("]");
        assert.ok(tabFrame.includes(tab.label), `tab navigation did not reach ${tab.label}`);
      }
      for (let tabPaneIndex = 0; tabPaneIndex < tab.panes.length; tabPaneIndex += 1) {
        const pane = tab.panes[tabPaneIndex];
        if (tabPaneIndex > 0) await presenter.press("j");
        const workspaceFrame = presenter.output.latest();
        assert.ok(workspaceFrame.includes(pane.id), `workspace view omitted selected pane ${pane.id}`);
        await presenter.press("enter");
        const detail = presenter.output.latest();
        assert.ok(detail.includes(pane.id), `detail did not identify ${pane.id}`);
        assert.match(detail, /RECENT OUTPUT|Recent output/);
        if (pane.id === "ws-1:p1") assert.ok(detail.includes("latest API output"));
        await presenter.press("f");
        focused.push(calls.filter((call) => call.method === "pane.focus").at(-1)?.params.pane_id);
        assert.equal(focused.at(-1), pane.id, `native focus did not target ${pane.id}`);
        if (["ws-1:p1", "ws-2:p5", "ws-3:p8"].includes(pane.id)) {
          const lower = await presenter.press(" ");
          if (pane.id === "ws-1:p1") assert.ok(lower.includes("Updated the API and added validation."));
          if (pane.id === "ws-2:p5") assert.ok(lower.includes("scripted backend unavailable"));
          if (pane.id === "ws-3:p8") assert.ok(lower.includes("no published recap"));
        }
        await presenter.press("escape");
      }
    }
  }

  assert.deepEqual(focused, model.paneOrder, "every native pane was reached and focused in stable-ID order");
  return presenter;
}

test("narrow Board user path reaches all 3 workspaces, all tabs/panes, live state and native focus without recap generation", async (t) => {
  const { model, workspaces, snapshot } = makeScenario();
  const files = await fixtureFiles(t, model);
  const socket = await scriptedServer(t, snapshot);
  const presenter = await driveEveryNativePane({ t, width: 48, rows: 13, defs: workspaces, model, files, socket, calls: socket.calls });
  assert.equal(presenter.input.isRaw, true);

  const marker = await readFile(files.recapMarker, "utf8").catch(() => "");
  assert.equal(marker, "", "opening, navigating, reading previews and focusing must never run the recap command");
  assert.deepEqual(socket.calls.filter((call) => call.method === "pane.focus").map((call) => call.params.pane_id), model.paneOrder);

  presenter.input.press("q");
  await presenter.promise;
  assert.equal(presenter.input.isRaw, false);
});

test("wide Mosaic user path represents every workspace/pane and focuses the same native IDs without recap generation", async (t) => {
  const { model, workspaces, snapshot } = makeScenario();
  const files = await fixtureFiles(t, model);
  const socket = await scriptedServer(t, snapshot);
  const presenter = await driveEveryNativePane({ t, width: 120, rows: 48, defs: workspaces, model, files, socket, calls: socket.calls });
  assert.deepEqual(socket.calls.filter((call) => call.method === "pane.focus").map((call) => call.params.pane_id), model.paneOrder);
  const marker = await readFile(files.recapMarker, "utf8").catch(() => "");
  assert.equal(marker, "", "Mosaic selection and native focus are passive recap readers");
  presenter.input.press("q");
  await presenter.promise;
});
