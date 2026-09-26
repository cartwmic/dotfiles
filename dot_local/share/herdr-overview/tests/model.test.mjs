import test from "node:test";
import assert from "node:assert/strict";
import { normalizeSnapshot } from "../src/model.mjs";

function snapshot() {
  return {
    version: "0.9.1",
    protocol: 22,
    focused_workspace_id: "ws-a",
    focused_tab_id: "ws-a:tab-1",
    focused_pane_id: "ws-a:pane-pi",
    workspaces: [{
      workspace_id: "ws-a", number: 1, label: "API", focused: true,
      pane_count: 3, tab_count: 1, active_tab_id: "ws-a:tab-1", agent_status: "working",
      worktree: null, tokens: {},
    }],
    tabs: [{
      tab_id: "ws-a:tab-1", workspace_id: "ws-a", number: 1, label: "Implement",
      focused: true, pane_count: 3, agent_status: "unknown",
    }],
    panes: [
      {
        pane_id: "ws-a:pane-shell", workspace_id: "ws-a", tab_id: "ws-a:tab-1",
        terminal_id: "term-shell", focused: false, agent_status: "unknown", revision: 1,
        label: null, title: "shell title", terminal_title_stripped: "shell", cwd: "/repo",
      },
      {
        pane_id: "ws-a:pane-pi", workspace_id: "ws-a", tab_id: "ws-a:tab-1",
        terminal_id: "term-pi", focused: true, agent_status: "working", revision: 2,
        agent: "pi", display_agent: "Pi", cwd: "/repo", foreground_cwd: "/repo/src",
        agent_session: { source: "herdr:pi", agent: "pi", kind: "id", value: "pi-session-1" },
      },
      {
        pane_id: "ws-a:pane-unknown", workspace_id: "ws-a", tab_id: "ws-a:tab-1",
        terminal_id: "term-unknown", focused: false, agent_status: "unknown", revision: 3,
        agent: null,
      },
    ],
    agents: [
      { pane_id: "ws-a:pane-pi", agent: "pi", display_agent: "Pi", agent_status: "working", agent_session: { agent: "pi", kind: "id", value: "pi-session-1" } },
      { pane_id: "ws-a:pane-unknown", agent: null, agent_status: "unknown" },
    ],
  };
}

test("normalizes the v0.9.1 snapshot by native IDs and shares Herdr focus", () => {
  const model = normalizeSnapshot(snapshot(), {}, {
    outputByPaneId: { "ws-a:pane-shell": "build ok", "ws-a:pane-pi": "working" },
    processByPaneId: { "ws-a:pane-shell": { foreground_processes: [{ name: "zsh" }] } },
  });

  assert.equal(model.protocol, 22);
  assert.deepEqual(model.selection, { workspaceId: "ws-a", tabId: "ws-a:tab-1", paneId: "ws-a:pane-pi" });
  assert.deepEqual(model.workspaces["ws-a"].tabIds, ["ws-a:tab-1"]);
  assert.deepEqual(model.tabs["ws-a:tab-1"].paneIds, ["ws-a:pane-shell", "ws-a:pane-pi", "ws-a:pane-unknown"]);
  assert.equal(model.panes["ws-a:pane-shell"].title, "shell title");
  assert.equal(model.panes["ws-a:pane-shell"].processInfo.foreground_processes[0].name, "zsh");
  assert.equal(model.panes["ws-a:pane-shell"].preview, "build ok");
  assert.equal(model.panes["ws-a:pane-shell"].agent.present, false);
  assert.equal(model.panes["ws-a:pane-shell"].agent.status, "unknown");
  assert.equal(model.panes["ws-a:pane-unknown"].agent.present, true);
  assert.equal(model.panes["ws-a:pane-unknown"].agent.recognized, false);
  assert.equal(model.panes["ws-a:pane-unknown"].agent.status, "unknown");
  assert.notEqual(model.panes["ws-a:pane-unknown"].agent.status, "done");
});

test("keeps supplied current prompt and published recap as separate fields from agent state", () => {
  const prompt = { session_id: "pi-session-1", text: "Continue the migration", working: true };
  const recap = { latest: { status: "published", summary: "Migration is in progress." }, lastAttempt: null };
  const model = normalizeSnapshot(snapshot(), {
    promptsBySessionId: { "pi-session-1": prompt },
    piRecapsBySessionId: { "pi-session-1": recap },
    workspaceRecaps: { "workspace:ws-a": { latest: { summary: "Workspace recap" }, lastAttempt: null } },
    sessionRecap: { latest: { summary: "Session recap" }, lastAttempt: null },
  });

  const pane = model.panes["ws-a:pane-pi"];
  assert.equal(pane.agent.status, "working");
  assert.equal(pane.prompt, prompt);
  assert.equal(pane.recap, recap);
  assert.notEqual(pane.prompt.text, pane.recap.latest.summary);
  assert.equal(model.workspaces["ws-a"].recap.latest.summary, "Workspace recap");
  assert.equal(model.recap.latest.summary, "Session recap");
});

test("rejects a server outside the pinned public protocol", () => {
  assert.throws(() => normalizeSnapshot({ ...snapshot(), protocol: 21 }), /protocol 22 required/);
});
