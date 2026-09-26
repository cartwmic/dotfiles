import test from "node:test";
import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { normalizeSnapshot } from "../src/model.mjs";
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
