import test from "node:test";
import assert from "node:assert/strict";
import net from "node:net";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { HerdrApi, HerdrApiError } from "../src/herdr-api.mjs";

async function fakeApi(t, snapshotProtocol = 22) {
  const root = await mkdtemp(path.join(os.tmpdir(), "herdr-overview-api-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const socketPath = path.join(root, "herdr.sock");
  const calls = [];
  const snapshot = { protocol: snapshotProtocol, version: "0.9.1", workspaces: [], tabs: [], panes: [], agents: [], layouts: [] };
  const server = net.createServer((socket) => {
    let buffer = "";
    socket.on("data", (chunk) => {
      buffer += chunk.toString("utf8");
      let newline;
      while ((newline = buffer.indexOf("\n")) >= 0) {
        const request = JSON.parse(buffer.slice(0, newline));
        buffer = buffer.slice(newline + 1);
        calls.push(request);
        let result = { type: "ok" };
        if (request.method === "session.snapshot") result = { type: "session_snapshot", snapshot };
        if (request.method === "pane.read") result = { type: "pane_read", read: { text: "recent output", pane_id: request.params.pane_id } };
        if (request.method === "pane.process_info") result = { type: "pane_process_info", process_info: { foreground_processes: [{ name: "zsh" }] } };
        if (request.method === "plugin.pane.open") result = { type: "plugin_pane_opened", plugin_pane: { plugin_id: "overview", pane: { pane_id: "ws:p-overview" } } };
        if (request.method === "events.subscribe") result = { type: "subscription_started" };
        socket.write(`${JSON.stringify({ id: request.id, result })}\n`);
        if (request.method === "events.subscribe") {
          setImmediate(() => socket.write(`${JSON.stringify({ event: "pane.output_matched", data: { pane_id: "ws:p1", read: { text: "subscribed output" } } })}\n`));
        }
      }
    });
  });
  await new Promise((resolve, reject) => server.listen(socketPath, (error) => error ? reject(error) : resolve()));
  t.after(() => new Promise((resolve) => server.close(resolve)));
  return { api: new HerdrApi({ socketPath }), calls };
}

test("uses the v0.9.1 public socket methods for snapshot, output, focus, rename, and plugin pane", async (t) => {
  const { api, calls } = await fakeApi(t);
  assert.equal((await api.snapshot()).protocol, 22);
  assert.equal(await api.readPane("ws:p1"), "recent output");
  assert.equal((await api.processInfo("ws:p1")).foreground_processes[0].name, "zsh");
  await api.focusPane("ws:p1");
  await api.renamePane("ws:p1", "Task");
  await api.renameTab("ws:t1", "Build");
  await api.resetDisplayName("pane", "ws:p1");
  await api.resetDisplayName("tab", "ws:t1");
  await api.closePane("ws:p-overview");
  await api.openOverviewPane();
  assert.deepEqual(calls.map((call) => call.method), [
    "session.snapshot", "pane.read", "pane.process_info", "pane.focus", "pane.rename", "tab.rename", "plugin.action.invoke", "plugin.action.invoke", "pane.close", "plugin.pane.open",
  ]);
  assert.deepEqual(calls.find((call) => call.method === "pane.focus").params, { pane_id: "ws:p1" });
  assert.deepEqual(calls.filter((call) => call.method === "plugin.action.invoke").map((call) => call.params), [
    { action_id: "overview.auto_name_pane", context: { focused_pane_id: "ws:p1" } },
    { action_id: "overview.auto_name_tab", context: { tab_id: "ws:t1" } },
  ]);
  assert.deepEqual(calls.find((call) => call.method === "plugin.pane.open").params, {
    plugin_id: "overview", entrypoint: "overview", placement: "tab", focus: false,
  });
});

test("subscribes through the public output-matched stream for pane output invalidation", async (t) => {
  const { api, calls } = await fakeApi(t);
  const received = new Promise((resolve) => {
    api.subscribe([{
      type: "pane.output_matched", pane_id: "ws:p1", source: "recent_unwrapped", lines: 12,
      match: { type: "regex", value: ".+" }, strip_ansi: true,
    }], resolve).then(({ close }) => { setTimeout(close, 20); });
  });
  const event = await received;
  assert.equal(event.event, "pane.output_matched");
  assert.equal(event.data.read.text, "subscribed output");
  assert.deepEqual(calls[0].params.subscriptions[0], {
    type: "pane.output_matched", pane_id: "ws:p1", source: "recent_unwrapped", lines: 12,
    match: { type: "regex", value: ".+" }, strip_ansi: true,
  });
});

test("fails closed when the connected server is not protocol 22", async (t) => {
  const { api } = await fakeApi(t, 21);
  await assert.rejects(api.snapshot(), /protocol 22 required/);
});

test("keeps Herdr API errors typed for callers", () => {
  const error = new HerdrApiError("not_found", "pane not found");
  assert.equal(error.code, "not_found");
  assert.equal(error.message, "pane not found");
});
