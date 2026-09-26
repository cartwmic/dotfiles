import { readFile } from "node:fs/promises";
import { readFileSync, watch } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const fixturePath = fileURLToPath(new URL("./palette-v0.9.1.json", import.meta.url));
export const PALETTE_FIXTURE = JSON.parse(readFileSync(fixturePath, "utf8"));
export const PALETTE_TOKENS = Object.freeze(Object.keys(PALETTE_FIXTURE.themes["catppuccin"]));

const ALIASES = new Map([
  ["catppuccin-mocha", "catppuccin"], ["latte", "catppuccin-latte"], ["light", "catppuccin-latte"],
  ["tokyonight", "tokyo-night"], ["tokyo-day", "tokyo-night-day"], ["tokyonight-day", "tokyo-night-day"],
  ["gruvbox-dark", "gruvbox"], ["onedark", "one-dark"], ["onelight", "one-light"],
  ["solarized-dark", "solarized"], ["lotus", "kanagawa-lotus"], ["rosepine", "rose-pine"],
  ["rosepine-dawn", "rose-pine-dawn"], ["dawn", "rose-pine-dawn"],
]);

function stripComment(line) {
  let quoted = false;
  let escaped = false;
  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    if (escaped) { escaped = false; continue; }
    if (quoted && char === "\\") { escaped = true; continue; }
    if (char === '"') quoted = !quoted;
    if (char === "#" && !quoted) return line.slice(0, index);
  }
  return line;
}

function tomlScalar(value) {
  const trimmed = value.trim();
  if (trimmed.startsWith('"') && trimmed.endsWith('"')) return JSON.parse(trimmed);
  if (trimmed.startsWith("'") && trimmed.endsWith("'")) return trimmed.slice(1, -1);
  if (trimmed === "true") return true;
  if (trimmed === "false") return false;
  return undefined;
}

export function parseThemeConfig(contents) {
  const config = { name: "catppuccin", auto_switch: false, custom: {}, mobile_width_threshold: 64 };
  let section = "";
  for (const rawLine of contents.split(/\r?\n/)) {
    const line = stripComment(rawLine).trim();
    if (!line) continue;
    const table = line.match(/^\[([^\]]+)\]$/);
    if (table) { section = table[1]; continue; }
    const pair = line.match(/^([A-Za-z0-9_-]+)\s*=\s*(.+)$/);
    if (!pair) continue;
    const [, key, rawValue] = pair;
    const value = tomlScalar(rawValue);
    if (section === "ui" && key === "mobile_width_threshold" && /^\d+$/.test(rawValue.trim())) {
      config.mobile_width_threshold = Number(rawValue.trim());
      continue;
    }
    if (value === undefined) continue;
    if (section === "theme" && ["name", "auto_switch", "dark_name", "light_name"].includes(key)) config[key] = value;
    else if (section === "theme.custom") config.custom[key] = value;
    else if (section === "theme.custom.dark" || section === "theme.custom.light") {
      const mode = section.slice("theme.custom.".length);
      config.custom[mode] ??= {};
      config.custom[mode][key] = value;
    }
  }
  return config;
}

function canonicalName(name) {
  const normalized = String(name ?? "catppuccin").toLowerCase().replace(/[ _]/g, "-");
  return ALIASES.get(normalized) ?? normalized;
}

function customColor(value) {
  const input = String(value).trim().toLowerCase();
  let hex = input;
  const rgb = input.match(/^rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)$/);
  if (rgb && rgb.slice(1).every((part) => Number(part) <= 255)) {
    hex = `#${rgb.slice(1).map((part) => Number(part).toString(16).padStart(2, "0")).join("")}`;
  } else if (/^#[0-9a-f]{3}$/.test(input)) {
    hex = `#${input.slice(1).split("").map((char) => char + char).join("")}`;
  }
  if (/^#[0-9a-f]{6}$/.test(hex)) return { kind: "rgb", hex };
  if (["reset", "default", "none", "transparent"].includes(input)) return { kind: "reset" };
  const ansiNames = new Set(["black", "red", "green", "yellow", "blue", "magenta", "purple", "cyan", "white", "gray", "grey", "darkgray", "darkgrey", "lightred", "lightgreen", "lightyellow", "lightblue", "lightmagenta", "lightcyan"]);
  return { kind: "ansi", name: ansiNames.has(input) ? (input === "purple" ? "magenta" : input) : "cyan" };
}

export function resolvePalette(config, appearance = null) {
  const autoSwitch = Boolean(config.auto_switch);
  const knownAppearance = !autoSwitch || appearance === "dark" || appearance === "light";
  const themeName = autoSwitch && appearance
    ? canonicalName(config[appearance === "light" ? "light_name" : "dark_name"] ?? config.name)
    : canonicalName(config.name);
  const base = PALETTE_FIXTURE.themes[themeName];
  if (!base) throw new Error(`unsupported Herdr v0.9.1 theme: ${themeName}`);

  const palette = structuredClone(base);
  for (const token of PALETTE_TOKENS) {
    if (typeof config.custom?.[token] === "string") palette[token] = customColor(config.custom[token]);
  }
  if (autoSwitch && appearance && config.custom?.[appearance]) {
    for (const token of PALETTE_TOKENS) {
      if (typeof config.custom[appearance][token] === "string") palette[token] = customColor(config.custom[appearance][token]);
    }
  }
  return {
    release: PALETTE_FIXTURE.attribution.release,
    protocol: PALETTE_FIXTURE.protocol,
    name: themeName,
    activeAppearanceKnown: knownAppearance,
    mobileWidthThreshold: Number.isInteger(config.mobile_width_threshold) ? config.mobile_width_threshold : 64,
    palette,
  };
}

export async function readThemeConfig(filePath = process.env.HERDR_CONFIG_PATH || path.join(process.env.HOME || "", ".config", "herdr", "config.toml")) {
  return parseThemeConfig(await readFile(filePath, "utf8"));
}

export async function readTheme(filePath) {
  return resolvePalette(await readThemeConfig(filePath));
}

export function watchThemeConfig(filePath, onChange, { debounceMs = 40 } = {}) {
  const filename = path.basename(filePath);
  let timer = null;
  let closed = false;
  const watcher = watch(path.dirname(filePath), (_event, changed) => {
    if (changed && changed.toString() !== filename) return;
    clearTimeout(timer);
    timer = setTimeout(async () => {
      if (closed) return;
      try {
        onChange(resolvePalette(await readThemeConfig(filePath)), null);
      } catch (error) {
        onChange(null, error);
      }
    }, debounceMs);
  });
  return () => {
    closed = true;
    clearTimeout(timer);
    watcher.close();
  };
}
