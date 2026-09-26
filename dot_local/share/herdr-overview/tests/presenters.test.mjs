import test from "node:test";
import assert from "node:assert/strict";
import { normalizeSnapshot } from "../src/model.mjs";
import { renderBoardDetail, renderBoardOverview, renderBoardWorkspace } from "../src/presenters/board.mjs";
import { renderMosaicDetail, renderMosaicOverview, renderMosaicWorkspace } from "../src/presenters/mosaic.mjs";

const NOW = Date.parse("2026-09-26T06:00:00Z");

function scenario() {
  const workspaces = [
    { id: "ws-1", label: "API", tabs: [
      { id: "ws-1:t1", label: "Build", panes: [
        { id: "ws-1:p1", label: "Pi task", agent: "pi", status: "working", cwd: "/repo/api", preview: "last output: migration running" },
        { id: "ws-1:p2", label: "Shell", cwd: "/repo/api/scripts", preview: "tests passed" },
      ] },
      { id: "ws-1:t2", label: "Review", panes: [
        { id: "ws-1:p3", label: "Unrecognized", agent: null, present: true, cwd: "/repo/review", preview: "waiting for input" },
      ] },
    ] },
    { id: "ws-2", label: "Web", tabs: [
      { id: "ws-2:t1", label: "Frontend", panes: [
        { id: "ws-2:p4", label: "Codex", agent: "codex", status: "blocked", cwd: "/repo/web", preview: "Approve the changes?" },
        { id: "ws-2:p5", label: "Pi docs", agent: "pi", status: "working", cwd: "/repo/docs", preview: "updating docs" },
      ] },
      { id: "ws-2:t2", label: "Checks", panes: [
        { id: "ws-2:p6", label: "Test shell", cwd: "/repo/web", preview: "lint complete" },
      ] },
    ] },
    { id: "ws-3", label: "Infra", tabs: [
      { id: "ws-3:t1", label: "Ops", panes: [
        { id: "ws-3:p7", label: "Deploy shell", cwd: "/repo/infra", preview: "plan ready" },
      ] },
      { id: "ws-3:t2", label: "Agent", panes: [
        { id: "ws-3:p8", label: "Pi recap", agent: "pi", status: "done", cwd: "/repo/infra", preview: "deployment completed" },
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
      agent_status: index === 1 ? "blocked" : "unknown",
    })),
    tabs: workspaces.flatMap((workspace) => workspace.tabs.map((tab) => ({
      tab_id: tab.id,
      workspace_id: workspace.id,
      number: Number(tab.id.split("t").at(-1)),
      label: tab.label,
      focused: tab.id === "ws-1:t1",
      agent_status: "unknown",
    }))),
    panes: workspaces.flatMap((workspace) => workspace.tabs.flatMap((tab) => tab.panes.map((pane, index) => ({
      pane_id: pane.id,
      workspace_id: workspace.id,
      tab_id: tab.id,
      terminal_id: `term-${pane.id}`,
      focused: pane.id === "ws-1:p1",
      agent_status: pane.status ?? "unknown",
      revision: index + 1,
      label: pane.label,
      title: `${pane.label} native title`,
      terminal_title_stripped: `${pane.label} terminal title`,
      cwd: pane.cwd,
      agent: pane.agent,
      ...(pane.agent === "pi" ? { agent_session: { source: "herdr:pi", agent: "pi", kind: "id", value: pane.id } } : {}),
    })))),
    agents: workspaces.flatMap((workspace) => workspace.tabs.flatMap((tab) => tab.panes
      .filter((pane) => pane.agent || pane.present)
      .map((pane) => ({
        pane_id: pane.id,
        agent: pane.agent,
        display_agent: pane.agent === "pi" ? "Pi" : pane.agent === "codex" ? "Codex" : null,
        agent_status: pane.status ?? "unknown",
        ...(pane.agent === "pi" ? { agent_session: { agent: "pi", kind: "id", value: pane.id } } : {}),
      })))),
  };
  const allPanes = workspaces.flatMap((workspace) => workspace.tabs.flatMap((tab) => tab.panes));
  const outputByPaneId = Object.fromEntries(allPanes.map((pane) => [pane.id, pane.preview]));
  const processByPaneId = Object.fromEntries(allPanes.map((pane) => [pane.id, {
    foreground_processes: [{ name: pane.agent === "pi" ? "pi" : pane.agent === "codex" ? "codex" : "zsh" }],
  }]));
  const promptsByPaneId = {
    "ws-1:p1": { text: "Continue the API migration", working: true, captured_at: new Date(NOW - 60_000).toISOString() },
    "ws-2:p5": { text: "Document the endpoint", working: true },
  };
  const piRecapsByPaneId = {
    "ws-1:p1": {
      latest: { record_id: "published-1", status: "published", summary: "Migrated the endpoint and updated validation.", published_at: new Date(NOW - 120_000).toISOString() },
      lastAttempt: { record_id: "published-1", status: "published" },
    },
    "ws-2:p5": {
      latest: null,
      lastAttempt: { record_id: "failed-1", status: "failed", created_at: new Date(NOW - 180_000).toISOString(), failure: { message: "scripted backend failed" } },
    },
    "ws-3:p8": { latest: null, lastAttempt: null },
  };
  const model = normalizeSnapshot(snapshot, {
    promptsByPaneId,
    piRecapsByPaneId,
    sessionRecap: {
      latest: { record_id: "session-1", status: "published", summary: "Endpoint migration is complete. Present state: review remains.", published_at: new Date(NOW - 60_000).toISOString() },
      lastAttempt: { record_id: "session-1", status: "published" },
    },
  }, { outputByPaneId, processByPaneId });
  const state = { model, journey: { level: "overview", workspaceId: "ws-1", tabId: "ws-1:t1", paneId: "ws-1:p1", detailScroll: 0 }, theme: { palette: {} } };
  return { state, workspaceDefs: workspaces, now: NOW };
}

function stripAnsi(value) {
  return value.replace(/\u001b\[[0-?]*[ -/]*[@-~]/g, "");
}

test("Board summarizes three workspaces, then keeps every tab and pane visible in grouped tiles", () => {
  const { state } = scenario();
  const overview = stripAnsi(renderBoardOverview(state, 48, 60, NOW));
  assert.match(overview, /API/);
  assert.match(overview, /Web/);
  assert.match(overview, /Infra/);
  assert.match(overview, /2 tabs · 3 panes/);
  assert.match(overview, /Herdr session recap/);
  assert.match(overview, /Endpoint migration is complete\.\s*Present state:\s*review remains\./);

  for (const workspaceId of state.model.workspaceOrder) {
    const workspace = stripAnsi(renderBoardWorkspace({ ...state, journey: { ...state.journey, level: "workspace", workspaceId } }, 48, 80));
    const workspaceModel = state.model.workspaces[workspaceId];
    for (const tabId of workspaceModel.tabIds) {
      const tab = state.model.tabs[tabId];
      assert.ok(workspace.includes(tab.label), `missing tab ${tab.label}`);
      for (const paneId of tab.paneIds) assert.ok(workspace.includes(paneId), `missing pane ${paneId}`);
    }
    if (workspaceId === "ws-1") {
      assert.match(workspace, /last output: migration running/);
      assert.match(workspace, /process pi/);
      assert.match(workspace, /title Pi task native title/);
      assert.match(workspace, /dir \/repo\/api/);
      assert.match(workspace, /agent unrecognized · unknown/);
      assert.doesNotMatch(workspace, /Unrecognized \[ws-1:p3\][\s\S]*done/);
    }
  }
});

test("Board pane detail puts recent output before separate prompt and recap, with real age/failure/missing states", () => {
  const { state } = scenario();
  const render = (paneId) => stripAnsi(renderBoardDetail({
    ...state,
    journey: { ...state.journey, level: "pane", workspaceId: state.model.panes[paneId].workspaceId, tabId: state.model.panes[paneId].tabId, paneId },
  }, 48, 60, NOW));
  const published = render("ws-1:p1");
  assert.ok(published.indexOf("Recent output") < published.indexOf("last output: migration running"));
  assert.ok(published.indexOf("last output: migration running") < published.indexOf("Current Pi prompt"));
  assert.ok(published.indexOf("Current Pi prompt") < published.indexOf("Latest recap"));
  assert.match(published, /Continue the API migration/);
  assert.match(published, /Migrated the endpoint and updated validation/);
  assert.match(published, /2m ago/);

  const failed = render("ws-2:p5");
  assert.match(failed, /Unavailable · last attempt failed/);
  assert.match(failed, /scripted backend failed/);
  const missing = render("ws-3:p8");
  assert.match(missing, /Unavailable · no published recap/);
  assert.match(missing, /deployment completed/);
});

test("Mosaic overview includes all workspace panes; opened workspace is tab-grouped and simultaneous", () => {
  const { state } = scenario();
  const overview = stripAnsi(renderMosaicOverview(state, 120, 80));
  for (const workspace of ["API", "Web", "Infra"]) assert.ok(overview.includes(workspace));
  for (const pane of state.model.paneOrder) assert.ok(overview.includes(pane), `Mosaic omitted ${pane}`);
  assert.match(overview, /Herdr session recap/);
  assert.match(overview, /Endpoint migration is complete\.\s*Present state:\s*review remains\./);

  const workspace = stripAnsi(renderMosaicWorkspace({ ...state, journey: { ...state.journey, level: "workspace", workspaceId: "ws-2", tabId: "ws-2:t1", paneId: "ws-2:p4" } }, 120, 80));
  assert.match(workspace, /Frontend/);
  assert.match(workspace, /Checks/);
  assert.match(workspace, /ws-2:p4/);
  assert.match(workspace, /ws-2:p5/);
  assert.match(workspace, /ws-2:p6/);
  assert.match(workspace, /Approve the changes\?/);
  assert.match(workspace, /updating docs/);
});

test("all-workspaces views keep the published Herdr-session recap in their fixed header", () => {
  const { state } = scenario();
  const stateWithoutSessionRecap = {
    ...state,
    model: {
      ...state.model,
      recap: { latest: null, lastAttempt: { record_id: "session-failed", status: "failed", failure: { message: "scripted group failure" } } },
    },
  };
  for (const overview of [
    renderBoardOverview(stateWithoutSessionRecap, 48, 16, NOW),
    renderMosaicOverview(stateWithoutSessionRecap, 120, 16, NOW),
  ]) {
    const plain = stripAnsi(overview);
    assert.match(plain, /Herdr session recap/);
    assert.match(plain, /Unavailable · last attempt failed/);
    assert.match(plain, /scripted group failure/);
  }
});

test("Mosaic detail keeps output, prompt, recap status and native metadata distinct", () => {
  const { state } = scenario();
  const detail = stripAnsi(renderMosaicDetail({ ...state, journey: { ...state.journey, level: "pane" } }, 120, 60, NOW));
  assert.ok(detail.indexOf("RECENT OUTPUT") < detail.indexOf("last output: migration running"));
  assert.ok(detail.indexOf("last output: migration running") < detail.indexOf("CURRENT PI PROMPT"));
  assert.ok(detail.indexOf("CURRENT PI PROMPT") < detail.indexOf("LATEST PUBLISHED RECAP"));
  assert.match(detail, /Continue the API migration/);
  assert.match(detail, /2m ago/);
  assert.match(detail, /Directory: \/repo\/api/);
  assert.match(stripAnsi(renderMosaicDetail({
    ...state,
    journey: { ...state.journey, level: "pane", workspaceId: "ws-2", tabId: "ws-2:t1", paneId: "ws-2:p5" },
  }, 120, 60, NOW)), /scripted backend failed/);
});

test("narrow and threshold-edge frames stay inside the active terminal width", () => {
  const { state } = scenario();
  const board = stripAnsi(renderBoardWorkspace({ ...state, journey: { ...state.journey, level: "workspace" } }, 48, 16));
  const mosaic = stripAnsi(renderMosaicDetail({ ...state, journey: { ...state.journey, level: "pane" } }, 65, 16, NOW));
  for (const [name, frame, width] of [["Board", board, 48], ["Mosaic", mosaic, 65]]) {
    for (const line of frame.split("\n")) assert.ok(line.length <= width, `${name} overflowed ${width} columns: ${line}`);
  }
});

test("a width/level-specific redraw does not mutate the common model or the other presenter's output", () => {
  const { state } = scenario();
  const before = structuredClone(state);
  const mosaicWorkspace = renderMosaicWorkspace({ ...state, journey: { ...state.journey, level: "workspace" } }, 120, 40);
  const boardDetail = renderBoardDetail({ ...state, journey: { ...state.journey, level: "pane" } }, 48, 40, NOW);

  renderBoardWorkspace({ ...state, journey: { ...state.journey, level: "workspace", paneId: "ws-1:p3" } }, 36, 8);
  renderMosaicDetail({ ...state, journey: { ...state.journey, level: "pane", detailScroll: 5 } }, 140, 12, NOW);

  assert.equal(renderMosaicWorkspace({ ...state, journey: { ...state.journey, level: "workspace" } }, 120, 40), mosaicWorkspace);
  assert.equal(renderBoardDetail({ ...state, journey: { ...state.journey, level: "pane" } }, 48, 40, NOW), boardDetail);
  assert.deepEqual(state, before);
});
