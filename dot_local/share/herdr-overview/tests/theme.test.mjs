import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { PALETTE_FIXTURE, PALETTE_TOKENS, parseThemeConfig, resolvePalette, watchThemeConfig } from "../src/theme.mjs";

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

test("fixture is attributed to the pinned Herdr source and contains every Palette token", () => {
  assert.equal(PALETTE_FIXTURE.attribution.project, "herdrdev/herdr");
  assert.equal(PALETTE_FIXTURE.attribution.release, "v0.9.1");
  assert.equal(PALETTE_FIXTURE.attribution.commit, "8544776216a8d28088db59a5344ea21ee2d05d2b");
  assert.equal(PALETTE_FIXTURE.protocol, 22);
  assert.equal(Object.keys(PALETTE_FIXTURE.themes).length, 18);
  assert.equal(PALETTE_TOKENS.length, 19);
  for (const [name, palette] of Object.entries(PALETTE_FIXTURE.themes)) {
    assert.deepEqual(Object.keys(palette).sort(), [...PALETTE_TOKENS].sort(), name);
  }
});

test("all rendered built-in palettes resolve exactly to the pinned v0.9.1 fixture", () => {
  for (const [name, expected] of Object.entries(PALETTE_FIXTURE.themes)) {
    assert.deepEqual(resolvePalette({ name, auto_switch: false, custom: {} }).palette, expected, name);
  }
});

test("reads Herdr's configured width threshold with the active theme", () => {
  const config = parseThemeConfig('[ui]\nmobile_width_threshold = 72\n[theme]\nname = "nord"\nauto_switch = false');
  assert.equal(resolvePalette(config).mobileWidthThreshold, 72);
});

test("reads [theme.custom] overrides without changing existing built-in tokens", () => {
  const config = parseThemeConfig(`
[theme]
name = "Tokyo Night"
auto_switch = false

[theme.custom]
surface_dim = "#24283B" # source-managed contrast override
accent = "rgb(1, 2, 3)"
`);
  const theme = resolvePalette(config);
  assert.equal(theme.name, "tokyo-night");
  assert.equal(theme.palette.surface_dim.hex, "#24283b");
  assert.deepEqual(theme.palette.accent, { kind: "rgb", hex: "#010203" });
  assert.deepEqual(theme.palette.text, PALETTE_FIXTURE.themes["tokyo-night"].text);
  assert.equal(theme.activeAppearanceKnown, true);
});

test("does not claim host auto-switch detection when config.toml has no active appearance", () => {
  const unresolved = resolvePalette({ name: "tokyo-night", auto_switch: true, dark_name: "tokyo-night", light_name: "tokyo-night-day", custom: {} });
  assert.equal(unresolved.activeAppearanceKnown, false);
  assert.equal(unresolved.name, "tokyo-night");
  const light = resolvePalette({
    name: "tokyo-night", auto_switch: true, dark_name: "tokyo-night", light_name: "catppuccin-latte",
    custom: { accent: "#010203", light: { text: "#040506" } },
  }, "light");
  assert.equal(light.activeAppearanceKnown, true);
  assert.equal(light.name, "catppuccin-latte");
  assert.deepEqual(light.palette.accent, { kind: "rgb", hex: "#010203" });
  assert.deepEqual(light.palette.text, { kind: "rgb", hex: "#040506" });
});

test("file watcher rereads config changes, including an atomic-style replacement", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "herdr-overview-theme-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const configPath = path.join(root, "config.toml");
  await writeFile(configPath, '[theme]\nname = "nord"\nauto_switch = false\n');
  const changed = new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("theme watcher did not report the update")), 2000);
    const stop = watchThemeConfig(configPath, (theme, error) => {
      if (error) { clearTimeout(timer); stop(); reject(error); return; }
      if (theme?.name === "dracula") { clearTimeout(timer); stop(); resolve(theme); }
    });
  });
  await delay(50);
  const replacement = path.join(root, "config.next");
  await writeFile(replacement, '[theme]\nname = "dracula"\nauto_switch = false\n[theme.custom]\naccent = "#010203"\n');
  await (await import("node:fs/promises")).rename(replacement, configPath);
  const theme = await changed;
  assert.equal(theme.name, "dracula");
  assert.deepEqual(theme.palette.accent, { kind: "rgb", hex: "#010203" });
  assert.equal((await readFile(configPath, "utf8")).includes("dracula"), true);
});
