import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

test("plugin manifest pins the minimum Herdr API and separates startup, pane, action, and event hooks", async () => {
  const manifest = await readFile(path.join(root, "herdr-plugin.toml"), "utf8");
  assert.match(manifest, /^id = "overview"/m);
  assert.match(manifest, /^min_herdr_version = "0\.9\.1"/m);
  assert.match(manifest, /\[\[startup\]\][\s\S]*command = \["node", "index\.mjs", "startup"\]/);
  assert.match(manifest, /\[\[actions\]\][\s\S]*id = "reconcile"[\s\S]*"node", "index\.mjs", "reconcile"/);
  assert.match(manifest, /id = "auto_name_pane"[\s\S]*contexts = \["pane"\][\s\S]*"node", "index\.mjs", "auto-name-pane"/);
  assert.match(manifest, /id = "auto_name_tab"[\s\S]*contexts = \["tab"\][\s\S]*"node", "index\.mjs", "auto-name-tab"/);
  assert.match(manifest, /\[\[panes\]\][\s\S]*id = "overview"[\s\S]*placement = "tab"/);
  for (const event of ["workspace.created", "tab.focused", "pane.focused", "pane.agent_status_changed", "pane.moved", "pane.exited"]) {
    assert.ok(manifest.includes(`on = "${event}"`), `missing ${event} hook`);
  }
});

test("desktop source boundaries exclude the native plugin package from Termux", async () => {
  const ignore = await readFile(path.resolve(root, "../../../.chezmoiignore"), "utf8");
  assert.match(ignore, /\.local\/share\/\*/);
  assert.match(ignore, /!\.local\/share\/passage-review/);
  assert.match(ignore, /{{- if ne \.profile "termux" }}/);
  assert.match(ignore, /\.config\n\.config\/\*\*/);
});
