import test from "node:test";
import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { normalizeSnapshot } from "../src/model.mjs";
import { evaluateDisplayNamePolicy } from "../src/display-name-policy.mjs";
import { readRecapFields } from "../src/recap-store.mjs";

async function writeJson(filePath, value) {
  await mkdir(path.dirname(filePath), { recursive: true });
  await writeFile(filePath, `${JSON.stringify(value)}\n`);
}

test("maps T1 prompt and recap fields by pane ID even without a native session reference", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "herdr-overview-recaps-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const sessionId = "pi/session one";
  const publishedId = "a".repeat(32);
  const failedId = "b".repeat(32);
  const workspaceId = "ws-native-3";
  const workspaceRecapId = "c".repeat(32);
  const records = [
    { record_id: publishedId, source_kind: "pi-session", source_id: sessionId, pane_id: `${workspaceId}:p1`, status: "published", summary: "Published recap", published_at: "2026-09-26T00:00:00Z" },
    { record_id: failedId, source_kind: "pi-session", source_id: sessionId, pane_id: `${workspaceId}:p1`, status: "failed", failure: { message: "backend failed" }, created_at: "2026-09-26T00:01:00Z" },
    { record_id: workspaceRecapId, source_kind: "workspace", source_id: workspaceId, status: "published", summary: "Workspace recap" },
    { record_id: "d".repeat(32), source_kind: "herdr-session", source_id: "active", status: "published", summary: "Session recap" },
  ];
  for (const record of records) await writeJson(path.join(root, "records", "2026-09-26", `${record.record_id}.json`), record);
  await writeJson(path.join(root, "latest.json"), {
    schema_version: 1,
    sources: [
      { source_kind: "pi-session", source_id: sessionId, latest_success_id: publishedId, last_attempt_id: failedId },
      { source_kind: "workspace", source_id: workspaceId, latest_success_id: workspaceRecapId, last_attempt_id: workspaceRecapId },
      { source_kind: "herdr-session", source_id: "active", latest_success_id: "d".repeat(32), last_attempt_id: "d".repeat(32) },
    ],
  });
  await writeJson(path.join(root, "prompts", "pi%2Fsession%20one.json"), {
    schema_version: 1, session_id: sessionId, pane_id: `${workspaceId}:p1`, text: "Fix the migration", working: true, captured_at: "2026-09-26T00:00:00Z",
  });

  const snapshot = {
    protocol: 22,
    version: "0.9.1",
    workspaces: [{ workspace_id: workspaceId, number: 1, label: "API", focused: true, pane_count: 1, tab_count: 1, active_tab_id: `${workspaceId}:t1`, agent_status: "working" }],
    tabs: [{ tab_id: `${workspaceId}:t1`, workspace_id: workspaceId, number: 1, label: "Main", focused: true, pane_count: 1, agent_status: "working" }],
    panes: [{ pane_id: `${workspaceId}:p1`, workspace_id: workspaceId, tab_id: `${workspaceId}:t1`, terminal_id: "term1", focused: true, agent_status: "working", revision: 1, agent: "pi" }],
    agents: [],
  };
  const supplied = await readRecapFields(snapshot, root);
  const model = normalizeSnapshot(snapshot, supplied);
  const pane = model.panes[`${workspaceId}:p1`];
  assert.equal(pane.prompt.text, "Fix the migration");
  assert.equal(pane.prompt.working, true);
  assert.equal(pane.recap.latest.summary, "Published recap");
  assert.equal(pane.recap.lastAttempt.status, "failed");
  assert.equal(model.workspaces[workspaceId].recap.latest.summary, "Workspace recap");
  assert.equal(model.recap.latest.summary, "Session recap");
  assert.notEqual(pane.prompt.text, pane.recap.latest.summary);
  assert.equal(pane.agent.status, "working");
});

test("maps manually published pane-source recaps into detail without using them for Pi naming", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "herdr-overview-manual-recap-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const paneId = "native-pane-7";
  const sessionId = "pi-session-7";
  const publishedId = "e".repeat(32);
  const failedId = "f".repeat(32);
  const published = {
    record_id: publishedId,
    source_kind: "manual",
    source_id: paneId,
    kind: "single",
    status: "published",
    summary: "Manual recap for this pane",
    created_at: "2026-09-27T12:00:00Z",
    published_at: "2026-09-27T12:01:00Z",
  };
  const failed = {
    record_id: failedId,
    source_kind: "manual",
    source_id: paneId,
    kind: "single",
    status: "failed",
    created_at: "2026-09-27T12:02:00Z",
    failure: { message: "manual recap backend failed" },
  };
  for (const record of [published, failed]) {
    await writeJson(path.join(root, "records", "2026-09-27", `${record.record_id}.json`), record);
  }
  await writeJson(path.join(root, "latest.json"), {
    schema_version: 1,
    sources: [{
      source_kind: "manual",
      source_id: paneId,
      latest_success_id: publishedId,
      last_attempt_id: failedId,
    }],
  });
  const snapshot = {
    protocol: 22,
    version: "0.9.1",
    focused_workspace_id: "workspace-7",
    focused_tab_id: "tab-7",
    focused_pane_id: paneId,
    workspaces: [{ workspace_id: "workspace-7", number: 1, label: "Keep workspace", focused: true, active_tab_id: "tab-7", agent_status: "unknown" }],
    tabs: [{ tab_id: "tab-7", workspace_id: "workspace-7", number: 1, label: "1", focused: true, pane_count: 1, agent_status: "unknown" }],
    panes: [{
      pane_id: paneId,
      workspace_id: "workspace-7",
      tab_id: "tab-7",
      focused: true,
      label: null,
      agent: "pi",
      agent_status: "unknown",
      agent_session: { agent: "pi", kind: "id", value: sessionId },
    }],
    agents: [],
  };

  const supplied = await readRecapFields(snapshot, root);
  const model = normalizeSnapshot(snapshot, supplied);
  assert.equal(model.panes[paneId].recap.latest.summary, "Manual recap for this pane");
  assert.equal(model.panes[paneId].recap.latest.source_kind, "manual");
  assert.equal(model.panes[paneId].recap.lastAttempt.status, "failed");
  assert.equal(model.panes[paneId].recap.lastAttempt.failure.message, "manual recap backend failed");
  assert.equal(model.panes[paneId].agent.status, "unknown");
  assert.equal(supplied.piRecapsByPaneId[paneId], undefined);
  assert.equal(evaluateDisplayNamePolicy(snapshot, { supplied }).rename.length, 0);
});
