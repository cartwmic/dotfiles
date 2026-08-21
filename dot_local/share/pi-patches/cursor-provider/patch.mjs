#!/usr/bin/env node
// chezmoi-pi-patch:cursor-provider
//
// RETIRED. Both chezmoi profiles load https://github.com/cartwmic/pi-sub, which
// has an in-tree Cursor provider. Desired state is unpatched on every profile,
// including axon-work-computer: restore leftover splices from backups / reverse
// the closed-union edits, and remove dropped cursor.ts. Do not apply the splice.
//
// EDITS_BY_FILE and payload/cursor.ts remain so restore can reverse a leftover
// work-machine splice. Targets are leftover agent-npm copies under
// ~/.pi/agent/npm/node_modules/@marckrenn if that tree still exists.
//
// Usage:
//   node patch.mjs [--check]
//
//   --check   Verify without writes; exit non-zero if splices or dropped
//             cursor.ts are still present.

import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
	copyFileSync,
	existsSync,
	mkdirSync,
	readFileSync,
	unlinkSync,
	writeFileSync,
} from "node:fs";
import { stripTypeScriptTypes } from "node:module";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const PATCH_REVISION = 1;

const PATCH_NAME = "cursor-provider";
const MARKER = `chezmoi-pi-patch:${PATCH_NAME} v${PATCH_REVISION}`;
const MARKER_PREFIX = `chezmoi-pi-patch:${PATCH_NAME}`;
const BACKUP_SUFFIX = ".orig.chezmoi-pi-patch";
const STATE_DIR = join(homedir(), ".local", "state", "chezmoi-pi-patches");
const STATE_FILE = join(STATE_DIR, `${PATCH_NAME}.json`);
const AGENT_MARCKRENN = join(homedir(), ".pi", "agent", "npm", "node_modules", "@marckrenn");
const HERE = dirname(fileURLToPath(import.meta.url));
const PAYLOAD_PATH = join(HERE, "payload", "cursor.ts");
const DEFAULT_MONTHLY_CAP_DOLLARS = 750;

const log = (msg) => console.log(`[pi-patch:${PATCH_NAME}] ${msg}`);
const warn = (msg) => console.warn(`[pi-patch:${PATCH_NAME}] WARN: ${msg}`);
const fail = (msg) => {
	console.error(`[pi-patch:${PATCH_NAME}] ERROR: ${msg}`);
	process.exit(1);
};

const checkOnly = process.argv.includes("--check");
const profile = process.env.PI_CHEZMOI_PROFILE ?? "";
// Retired: never splice. Restore leftovers on every profile, including work.
const wantPatched = false;

const T = (n) => "\t".repeat(n);

// ─── Edit definitions ──────────────────────────────────────────────────────
//
// Each `find` MUST appear exactly once in the unpatched file. Each `replace`
// carries MARKER so we can detect "already patched" and reverse the edit.
// Any change here requires a PATCH_REVISION bump.

const EDITS_BY_FILE = {
	shared: [
		{
			name: "shared PROVIDERS — add cursor",
			find: `export const PROVIDERS = ["anthropic", "copilot", "gemini", "antigravity", "codex", "kiro", "zai"] as const;`,
			replace: `export const PROVIDERS = ["anthropic", "copilot", "gemini", "antigravity", "codex", "kiro", "zai", "cursor"] as const; // ${MARKER}`,
		},
		{
			name: "shared CoreProviderSettings — optional monthlyCapDollars",
			find: [
				"export interface CoreProviderSettings {",
				`${T(1)}enabled: ProviderEnabledSetting;`,
				`${T(1)}displayName?: string;`,
				`${T(1)}fetchStatus: boolean;`,
				`${T(1)}extraUsageCurrencySymbol?: string;`,
				`${T(1)}extraUsageDecimalSeparator?: "." | ",";`,
				"}",
			].join("\n"),
			replace: [
				"export interface CoreProviderSettings {",
				`${T(1)}enabled: ProviderEnabledSetting;`,
				`${T(1)}displayName?: string;`,
				`${T(1)}fetchStatus: boolean;`,
				`${T(1)}extraUsageCurrencySymbol?: string;`,
				`${T(1)}extraUsageDecimalSeparator?: "." | ",";`,
				`${T(1)}/** Operator included monthly cap in dollars (Cursor). // ${MARKER} */`,
				`${T(1)}monthlyCapDollars?: number;`,
				"}",
			].join("\n"),
		},
		{
			name: "shared CoreProviderSettingsMap — add cursor",
			find: [
				"export interface CoreProviderSettingsMap {",
				`${T(1)}anthropic: CoreProviderSettings;`,
				`${T(1)}copilot: CoreProviderSettings;`,
				`${T(1)}gemini: CoreProviderSettings;`,
				`${T(1)}antigravity: CoreProviderSettings;`,
				`${T(1)}codex: CoreProviderSettings;`,
				`${T(1)}kiro: CoreProviderSettings;`,
				`${T(1)}zai: CoreProviderSettings;`,
				"}",
			].join("\n"),
			replace: [
				"export interface CoreProviderSettingsMap {",
				`${T(1)}anthropic: CoreProviderSettings;`,
				`${T(1)}copilot: CoreProviderSettings;`,
				`${T(1)}gemini: CoreProviderSettings;`,
				`${T(1)}antigravity: CoreProviderSettings;`,
				`${T(1)}codex: CoreProviderSettings;`,
				`${T(1)}kiro: CoreProviderSettings;`,
				`${T(1)}zai: CoreProviderSettings;`,
				`${T(1)}cursor: CoreProviderSettings; // ${MARKER}`,
				"}",
			].join("\n"),
		},
		{
			name: "shared getDefaultCoreProviderSettings — cursor monthlyCapDollars default 750",
			find: [
				`${T(2)}defaults[provider] = {`,
				`${T(3)}enabled: "auto" as ProviderEnabledSetting,`,
				`${T(3)}fetchStatus: Boolean(PROVIDER_METADATA[provider]?.status),`,
				`${T(2)}};`,
			].join("\n"),
			replace: [
				`${T(2)}defaults[provider] = {`,
				`${T(3)}enabled: "auto" as ProviderEnabledSetting,`,
				`${T(3)}fetchStatus: Boolean(PROVIDER_METADATA[provider]?.status),`,
				`${T(3)}// ${MARKER} — fetch reads providers.cursor.monthlyCapDollars; default ${DEFAULT_MONTHLY_CAP_DOLLARS}`,
				`${T(3)}...(provider === "cursor" ? { monthlyCapDollars: ${DEFAULT_MONTHLY_CAP_DOLLARS} } : {}),`,
				`${T(2)}};`,
			].join("\n"),
		},
		{
			name: "shared PROVIDER_METADATA.cursor — detection tokens",
			find: [
				`${T(1)}zai: {`,
				`${T(2)}displayName: "z.ai",`,
				`${T(2)}detection: { providerTokens: ["zai", "z.ai", "xai"], modelTokens: [] },`,
				`${T(1)}},`,
				"};",
			].join("\n"),
			replace: [
				`${T(1)}zai: {`,
				`${T(2)}displayName: "z.ai",`,
				`${T(2)}detection: { providerTokens: ["zai", "z.ai", "xai"], modelTokens: [] },`,
				`${T(1)}},`,
				`${T(1)}cursor: {`,
				`${T(2)}// ${MARKER}`,
				`${T(2)}displayName: "Cursor",`,
				`${T(2)}detection: { providerTokens: ["cursor"], modelTokens: ["cursor", "grok"] },`,
				`${T(1)}},`,
				"};",
			].join("\n"),
		},
	],
	registry: [
		{
			name: "core registry — export CursorProvider",
			find: `export { ZaiProvider } from "./impl/zai.js";`,
			replace: [
				`export { ZaiProvider } from "./impl/zai.js";`,
				`export { CursorProvider } from "./impl/cursor.js"; // ${MARKER}`,
			].join("\n"),
		},
		{
			name: "core registry — import CursorProvider",
			find: `import { ZaiProvider } from "./impl/zai.js";`,
			replace: [
				`import { ZaiProvider } from "./impl/zai.js";`,
				`import { CursorProvider } from "./impl/cursor.js"; // ${MARKER}`,
			].join("\n"),
		},
		{
			name: "core registry — PROVIDER_FACTORIES.cursor",
			find: [
				"const PROVIDER_FACTORIES: Record<ProviderName, () => UsageProvider> = {",
				`${T(1)}anthropic: () => new AnthropicProvider(),`,
				`${T(1)}copilot: () => new CopilotProvider(),`,
				`${T(1)}gemini: () => new GeminiProvider(),`,
				`${T(1)}antigravity: () => new AntigravityProvider(),`,
				`${T(1)}codex: () => new CodexProvider(),`,
				`${T(1)}kiro: () => new KiroProvider(),`,
				`${T(1)}zai: () => new ZaiProvider(),`,
				"};",
			].join("\n"),
			replace: [
				"const PROVIDER_FACTORIES: Record<ProviderName, () => UsageProvider> = {",
				`${T(1)}anthropic: () => new AnthropicProvider(),`,
				`${T(1)}copilot: () => new CopilotProvider(),`,
				`${T(1)}gemini: () => new GeminiProvider(),`,
				`${T(1)}antigravity: () => new AntigravityProvider(),`,
				`${T(1)}codex: () => new CodexProvider(),`,
				`${T(1)}kiro: () => new KiroProvider(),`,
				`${T(1)}zai: () => new ZaiProvider(),`,
				`${T(1)}cursor: () => new CursorProvider(), // ${MARKER}`,
				"};",
			].join("\n"),
		},
	],
	settingsTypes: [
		{
			name: "bar CursorProviderSettings + ProviderSettingsMap.cursor",
			find: [
				"export interface ZaiProviderSettings extends BaseProviderSettings {",
				`${T(1)}windows: {`,
				`${T(2)}showTokens: boolean;`,
				`${T(2)}showMonthly: boolean;`,
				`${T(1)}};`,
				"}",
				"",
				"export interface ProviderSettingsMap {",
				`${T(1)}anthropic: AnthropicProviderSettings;`,
				`${T(1)}copilot: CopilotProviderSettings;`,
				`${T(1)}gemini: GeminiProviderSettings;`,
				`${T(1)}antigravity: AntigravityProviderSettings;`,
				`${T(1)}codex: CodexProviderSettings;`,
				`${T(1)}kiro: KiroProviderSettings;`,
				`${T(1)}zai: ZaiProviderSettings;`,
				"}",
			].join("\n"),
			replace: [
				"export interface ZaiProviderSettings extends BaseProviderSettings {",
				`${T(1)}windows: {`,
				`${T(2)}showTokens: boolean;`,
				`${T(2)}showMonthly: boolean;`,
				`${T(1)}};`,
				"}",
				"",
				`/** Cursor bar settings. Cap lives on core monthlyCapDollars; no window toggles. // ${MARKER} */`,
				"export interface CursorProviderSettings extends BaseProviderSettings {}",
				"",
				"export interface ProviderSettingsMap {",
				`${T(1)}anthropic: AnthropicProviderSettings;`,
				`${T(1)}copilot: CopilotProviderSettings;`,
				`${T(1)}gemini: GeminiProviderSettings;`,
				`${T(1)}antigravity: AntigravityProviderSettings;`,
				`${T(1)}codex: CodexProviderSettings;`,
				`${T(1)}kiro: KiroProviderSettings;`,
				`${T(1)}zai: ZaiProviderSettings;`,
				`${T(1)}cursor: CursorProviderSettings;`,
				"}",
			].join("\n"),
		},
		{
			name: "bar getDefaultSettings — cursor defaults",
			find: [
				`${T(3)}zai: {`,
				`${T(4)}showStatus: false,`,
				`${T(4)}windows: {`,
				`${T(5)}showTokens: true,`,
				`${T(5)}showMonthly: true,`,
				`${T(4)}},`,
				`${T(3)}},`,
				`${T(2)}},`,
				`${T(2)}display: {`,
			].join("\n"),
			replace: [
				`${T(3)}zai: {`,
				`${T(4)}showStatus: false,`,
				`${T(4)}windows: {`,
				`${T(5)}showTokens: true,`,
				`${T(5)}showMonthly: true,`,
				`${T(4)}},`,
				`${T(3)}},`,
				`${T(3)}cursor: {`,
				`${T(4)}// ${MARKER}`,
				`${T(4)}showStatus: true,`,
				`${T(3)}},`,
				`${T(2)}},`,
				`${T(2)}display: {`,
			].join("\n"),
		},
	],
	barMetadata: [
		{
			name: "bar cursorWindowVisible — billing-cycle window always shown when enabled",
			find: [
				`const zaiWindowVisible: ProviderMetadata["isWindowVisible"] = (_usage, window, settings, _model) => {`,
				`${T(1)}if (!settings) return true;`,
				`${T(1)}const ps = settings.providers.zai;`,
				`${T(1)}if (window.label === "Tokens") return ps.windows.showTokens;`,
				`${T(1)}if (window.label === "Monthly") return ps.windows.showMonthly;`,
				`${T(1)}return true;`,
				"};",
			].join("\n"),
			replace: [
				`const zaiWindowVisible: ProviderMetadata["isWindowVisible"] = (_usage, window, settings, _model) => {`,
				`${T(1)}if (!settings) return true;`,
				`${T(1)}const ps = settings.providers.zai;`,
				`${T(1)}if (window.label === "Tokens") return ps.windows.showTokens;`,
				`${T(1)}if (window.label === "Monthly") return ps.windows.showMonthly;`,
				`${T(1)}return true;`,
				"};",
				"",
				`// ${MARKER} — single billing-cycle window; always visible when the provider is enabled.`,
				`const cursorWindowVisible: ProviderMetadata["isWindowVisible"] = () => true;`,
			].join("\n"),
		},
		{
			name: "bar PROVIDER_METADATA.cursor window handler",
			find: [
				`${T(1)}zai: {`,
				`${T(2)}...BASE_METADATA.zai,`,
				`${T(2)}isWindowVisible: zaiWindowVisible,`,
				`${T(1)}},`,
				"};",
			].join("\n"),
			replace: [
				`${T(1)}zai: {`,
				`${T(2)}...BASE_METADATA.zai,`,
				`${T(2)}isWindowVisible: zaiWindowVisible,`,
				`${T(1)}},`,
				`${T(1)}cursor: {`,
				`${T(2)}// ${MARKER}`,
				`${T(2)}...BASE_METADATA.cursor,`,
				`${T(2)}isWindowVisible: cursorWindowVisible,`,
				`${T(1)}},`,
				"};",
			].join("\n"),
		},
	],
	barUi: [
		{
			name: "bar cursor monthly-cap control writes core monthlyCapDollars",
			find: [
				`${T(5)}items.unshift({`,
				`${T(6)}id: "enabled",`,
				`${T(6)}label: "Enabled",`,
				`${T(6)}currentValue: enabledValue,`,
				`${T(6)}values: ["auto", "on", "off"],`,
				`${T(6)}description: "Auto enables if credentials are detected.",`,
				`${T(5)}});`,
				`${T(5)}const handleChange = (id: string, value: string) => {`,
				`${T(6)}if (id === "enabled") {`,
				`${T(7)}const nextEnabled = value === "auto" ? "auto" : value === "on";`,
				`${T(7)}coreProvider.enabled = nextEnabled;`,
				`${T(7)}if (onCoreSettingsChange) {`,
				`${T(8)}const patch = {`,
				`${T(9)}providers: {`,
				`${T(10)}[providerCategory]: { enabled: nextEnabled },`,
				`${T(9)}},`,
				`${T(8)}} as unknown as Partial<CoreSettings>;`,
				`${T(8)}void onCoreSettingsChange(patch, coreSettings);`,
				`${T(7)}}`,
				`${T(7)}return;`,
				`${T(6)}}`,
				`${T(6)}settings = applyProviderSettingsChange(settings, providerCategory, id, value);`,
			].join("\n"),
			replace: [
				`${T(5)}items.unshift({`,
				`${T(6)}id: "enabled",`,
				`${T(6)}label: "Enabled",`,
				`${T(6)}currentValue: enabledValue,`,
				`${T(6)}values: ["auto", "on", "off"],`,
				`${T(6)}description: "Auto enables if credentials are detected.",`,
				`${T(5)}});`,
				`${T(5)}if (providerCategory === "cursor") {`,
				`${T(6)}// ${MARKER} — operator editor for core providers.cursor.monthlyCapDollars`,
				`${T(6)}const capValue = coreProvider.monthlyCapDollars;`,
				`${T(6)}const capCurrent = typeof capValue === "number" && Number.isFinite(capValue) && capValue > 0`,
				`${T(7)}? String(Math.round(capValue))`,
				`${T(7)}: "${DEFAULT_MONTHLY_CAP_DOLLARS}";`,
				`${T(6)}items.push({`,
				`${T(7)}id: "monthlyCapDollars",`,
				`${T(7)}label: "Monthly Included Cap ($)",`,
				`${T(7)}currentValue: capCurrent,`,
				`${T(7)}values: ["200", "500", "750", "1000", CUSTOM_OPTION],`,
				`${T(7)}description: "Included Cursor monthly cap used for used-percent. Default ${DEFAULT_MONTHLY_CAP_DOLLARS}.",`,
				`${T(7)}submenu: buildInputSubmenu(`,
				`${T(8)}"Monthly Included Cap ($)",`,
				`${T(8)}(value) => parseInteger(value, 1, 100000),`,
				`${T(8)}undefined,`,
				`${T(8)}"Included monthly cap in dollars. Default ${DEFAULT_MONTHLY_CAP_DOLLARS}.",`,
				`${T(7)}),`,
				`${T(6)}});`,
				`${T(5)}}`,
				`${T(5)}const handleChange = (id: string, value: string) => {`,
				`${T(6)}if (id === "enabled") {`,
				`${T(7)}const nextEnabled = value === "auto" ? "auto" : value === "on";`,
				`${T(7)}coreProvider.enabled = nextEnabled;`,
				`${T(7)}if (onCoreSettingsChange) {`,
				`${T(8)}const patch = {`,
				`${T(9)}providers: {`,
				`${T(10)}[providerCategory]: { enabled: nextEnabled },`,
				`${T(9)}},`,
				`${T(8)}} as unknown as Partial<CoreSettings>;`,
				`${T(8)}void onCoreSettingsChange(patch, coreSettings);`,
				`${T(7)}}`,
				`${T(7)}return;`,
				`${T(6)}}`,
				`${T(6)}if (id === "monthlyCapDollars") {`,
				`${T(7)}if (value === CUSTOM_OPTION) return;`,
				`${T(7)}const cap = Number.parseInt(value, 10);`,
				`${T(7)}if (!Number.isFinite(cap) || cap <= 0) return;`,
				`${T(7)}coreProvider.monthlyCapDollars = cap;`,
				`${T(7)}if (onCoreSettingsChange) {`,
				`${T(8)}const patch = {`,
				`${T(9)}providers: {`,
				`${T(10)}[providerCategory]: { monthlyCapDollars: cap },`,
				`${T(9)}},`,
				`${T(8)}} as unknown as Partial<CoreSettings>;`,
				`${T(8)}void onCoreSettingsChange(patch, coreSettings);`,
				`${T(7)}}`,
				`${T(7)}return;`,
				`${T(6)}}`,
				`${T(6)}settings = applyProviderSettingsChange(settings, providerCategory, id, value);`,
			].join("\n"),
		},
	],
};

const FILE_SPECS = [
	{
		key: "shared",
		pkg: "pi-sub-shared",
		rel: "index.ts",
		edits: EDITS_BY_FILE.shared,
	},
	{
		key: "registry",
		pkg: "pi-sub-core",
		rel: "src/providers/registry.ts",
		edits: EDITS_BY_FILE.registry,
	},
	{
		key: "settingsTypes",
		pkg: "pi-sub-bar",
		rel: "src/settings-types.ts",
		edits: EDITS_BY_FILE.settingsTypes,
	},
	{
		key: "barMetadata",
		pkg: "pi-sub-bar",
		rel: "src/providers/metadata.ts",
		edits: EDITS_BY_FILE.barMetadata,
	},
	{
		key: "barUi",
		pkg: "pi-sub-bar",
		rel: "src/settings/ui.ts",
		edits: EDITS_BY_FILE.barUi,
	},
];

const DROP_REL = "src/providers/impl/cursor.ts";

// ─── Helpers ───────────────────────────────────────────────────────────────

const sha256 = (s) => createHash("sha256").update(s).digest("hex");
const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const countMarker = (s, marker) => (s.match(new RegExp(escapeRe(marker), "g")) || []).length;

function countOccurrences(haystack, needle) {
	if (needle.length === 0) return 0;
	let count = 0;
	let idx = haystack.indexOf(needle);
	while (idx !== -1) {
		count += 1;
		idx = haystack.indexOf(needle, idx + needle.length);
	}
	return count;
}

function agentPkgFile(pkg, rel) {
	return join(AGENT_MARCKRENN, pkg, rel);
}

function locateTargets() {
	const files = [];
	for (const spec of FILE_SPECS) {
		const path = agentPkgFile(spec.pkg, spec.rel);
		if (!existsSync(path)) return null;
		files.push({ ...spec, path });
	}
	const dropPath = agentPkgFile("pi-sub-core", DROP_REL);
	const dropDir = dirname(dropPath);
	if (!existsSync(dropDir)) return null;
	return { files, dropPath };
}

function readPkgVersion(pkg) {
	try {
		const pkgJson = JSON.parse(readFileSync(join(AGENT_MARCKRENN, pkg, "package.json"), "utf8"));
		return pkgJson.version ?? null;
	} catch {
		return null;
	}
}

function getInstalledVersions() {
	return {
		piSubShared: readPkgVersion("pi-sub-shared"),
		piSubCore: readPkgVersion("pi-sub-core"),
		piSubBar: readPkgVersion("pi-sub-bar"),
	};
}

function writeStateFile(payload) {
	try {
		mkdirSync(STATE_DIR, { recursive: true });
		writeFileSync(
			STATE_FILE,
			JSON.stringify(
				{
					...payload,
					patchName: PATCH_NAME,
					marker: MARKER,
					when: new Date().toISOString(),
				},
				null,
				2,
			) + "\n",
		);
	} catch {
		/* best-effort */
	}
}

function validateTypeScript(label, content) {
	if (typeof stripTypeScriptTypes !== "function") {
		fail("Node stripTypeScriptTypes is required (Node 22.7+/24) to validate TypeScript splices");
	}
	let stripped;
	try {
		stripped = stripTypeScriptTypes(content, { mode: "strip", sourceUrl: label });
	} catch (err) {
		fail(`type-strip failed for ${label}: ${err && err.message ? err.message : String(err)}`);
	}
	return stripped;
}

function writeValidated(targetPath, content) {
	const tmpTs = `${targetPath}.chezmoi-pi-patch.tmp.ts`;
	const tmpJs = `${targetPath}.chezmoi-pi-patch.tmp.js`;
	writeFileSync(tmpTs, content, "utf8");
	try {
		const stripped = validateTypeScript(targetPath, content);
		writeFileSync(tmpJs, stripped, "utf8");
		try {
			execFileSync(process.execPath, ["--check", tmpJs], { stdio: "pipe" });
		} catch (err) {
			const stderr = err.stderr ? err.stderr.toString() : String(err);
			fail(`syntax error after rewrite — target left untouched. node --check output:\n${stderr}`);
		}
		execFileSync("mv", [tmpTs, targetPath]);
	} finally {
		try {
			unlinkSync(tmpJs);
		} catch {
			/* best effort */
		}
		try {
			if (existsSync(tmpTs)) unlinkSync(tmpTs);
		} catch {
			/* best effort */
		}
	}
}

function backupPath(targetPath) {
	return `${targetPath}${BACKUP_SUFFIX}`;
}

function ensureBackup(targetPath) {
	const backup = backupPath(targetPath);
	if (!existsSync(backup)) {
		copyFileSync(targetPath, backup);
		log(`backup written: ${backup}`);
	}
	return backup;
}

function restoreFromBackupOrReverse(targetPath, original, edits) {
	const backup = backupPath(targetPath);
	if (existsSync(backup)) {
		return readFileSync(backup, "utf8");
	}
	let reverted = original;
	for (const edit of [...edits].reverse()) {
		reverted = reverted.replace(edit.replace, edit.find);
	}
	if (reverted.includes(MARKER_PREFIX)) {
		fail(
			`stale/partial marker in ${targetPath} and no backup at ${backup}; reverse-edit failed. Reinstall @marckrenn/pi-sub-* and re-run chezmoi apply.`,
		);
	}
	return reverted;
}

function fileIsCurrent(content, edits) {
	return countMarker(content, MARKER) === edits.length;
}

function applyEdits(content, edits, path) {
	for (const edit of edits) {
		const occurrences = countOccurrences(content, edit.find);
		if (occurrences !== 1) {
			fail(
				`anchor for edit "${edit.name}" found ${occurrences} times (expected 1) in ${path}. ` +
					`Upstream likely changed the closed-union shape — update patch.mjs anchors and bump PATCH_REVISION.`,
			);
		}
	}
	let patched = content;
	for (const edit of edits) patched = patched.replace(edit.find, edit.replace);
	return patched;
}

function dropIsCurrent(dropPath) {
	if (!existsSync(dropPath)) return false;
	return readFileSync(dropPath, "utf8").includes(MARKER_PREFIX);
}

function readPayload() {
	if (!existsSync(PAYLOAD_PATH)) {
		fail(`payload missing at ${PAYLOAD_PATH}`);
	}
	const payload = readFileSync(PAYLOAD_PATH, "utf8");
	if (!payload.includes(MARKER_PREFIX)) {
		fail(`payload at ${PAYLOAD_PATH} is missing marker ${MARKER_PREFIX}`);
	}
	return payload;
}

// ─── Locate ────────────────────────────────────────────────────────────────

const located = locateTargets();
if (!located) {
	if (checkOnly) fail("pi-loaded @marckrenn/pi-sub-{shared,core,bar} not installed under ~/.pi/agent/npm; cannot verify patch");
	log("pi-sub packages not installed under ~/.pi/agent/npm — nothing to patch");
	process.exit(0);
}

const { files, dropPath } = located;
log(`profile=${profile || "(unset)"} agent-npm: ${AGENT_MARCKRENN}`);
log(`drop target: ${dropPath}`);

const versions = getInstalledVersions();

// ─── Desired state is UNPATCHED on every profile (patch retired) ──────

if (!wantPatched) {
	const spliceHasMarker = files.some((file) => readFileSync(file.path, "utf8").includes(MARKER_PREFIX));
	const dropExists = existsSync(dropPath);
	if (checkOnly) {
		if (spliceHasMarker) fail(`desired state is unpatched but spliced files are patched (profile=${profile || "(unset)"})`);
		if (dropExists) fail(`desired state is unpatched but ${dropPath} exists (profile=${profile || "(unset)"})`);
		log("retired: targets unpatched as expected on every profile");
		process.exit(0);
	}
	if (!spliceHasMarker && !dropExists) {
		log("retired: nothing to restore; already unpatched");
		writeStateFile({ status: "unpatched", target: dropPath, reason: `retired profile=${profile || "(unset)"}` });
		process.exit(0);
	}
	for (const file of files) {
		const original = readFileSync(file.path, "utf8");
		if (!original.includes(MARKER_PREFIX)) continue;
		const restored = restoreFromBackupOrReverse(file.path, original, file.edits);
		if (restored !== original) writeValidated(file.path, restored);
		log(`retired: restored ${file.path}`);
	}
	if (existsSync(dropPath)) {
		unlinkSync(dropPath);
		log(`retired: removed dropped ${dropPath}`);
	}
	writeStateFile({ status: "unpatched", target: dropPath, reason: `retired profile=${profile || "(unset)"}` });
	process.exit(0);
}

// Unreachable: wantPatched is always false. Left in place so EDITS_BY_FILE can
// still reverse a leftover splice; do not set wantPatched back to a profile gate.

// ─── Gate: profile IS axon-work-computer → desired state is PATCHED ────────

const snapshots = files.map((file) => {
	const original = readFileSync(file.path, "utf8");
	return {
		...file,
		original,
		current: fileIsCurrent(original, file.edits),
		hasAny: original.includes(MARKER_PREFIX),
	};
});

const allSplicesCurrent = snapshots.every((file) => file.current);
const dropCurrent = dropIsCurrent(dropPath);

if (allSplicesCurrent && dropCurrent) {
	for (const file of snapshots) {
		const count = countMarker(file.original, MARKER);
		if (count !== file.edits.length) {
			warn(`${file.path}: marker count (${count}) ≠ expected (${file.edits.length}); file may be partially patched`);
		}
	}
	if (checkOnly) {
		log(`already patched at revision ${PATCH_REVISION}`);
		process.exit(0);
	}
	writeStateFile({
		status: "already-patched",
		target: dropPath,
		versions,
		patchRevision: PATCH_REVISION,
	});
	log(`already patched at revision ${PATCH_REVISION} — no-op`);
	process.exit(0);
}

if (checkOnly) {
	fail(`install is unpatched or stale at revision ${PATCH_REVISION}`);
}

if (!existsSync(PAYLOAD_PATH)) {
	fail(`payload missing at ${PAYLOAD_PATH}`);
}

const writes = [];

for (const file of snapshots) {
	if (file.current) continue;
	let content = file.original;
	if (file.hasAny) {
		log(`stale/partial patch in ${file.path}; restoring before re-apply`);
		content = restoreFromBackupOrReverse(file.path, file.original, file.edits);
	}
	const patched = applyEdits(content, file.edits, file.path);
	const markerCountAfter = countMarker(patched, MARKER);
	if (markerCountAfter !== file.edits.length) {
		fail(`planned marker count ${markerCountAfter} ≠ expected ${file.edits.length} for ${file.path}`);
	}
	writes.push({ path: file.path, original: file.original, content: patched, backup: true });
}

if (!dropCurrent) {
	writes.push({ path: dropPath, original: existsSync(dropPath) ? readFileSync(dropPath, "utf8") : "", content: readPayload(), backup: false });
}

for (const write of writes) {
	validateTypeScript(write.path, write.content);
	const tmpJs = `${write.path}.chezmoi-pi-patch.precheck.js`;
	writeFileSync(tmpJs, stripTypeScriptTypes(write.content, { mode: "strip", sourceUrl: write.path }), "utf8");
	try {
		execFileSync(process.execPath, ["--check", tmpJs], { stdio: "pipe" });
	} catch (err) {
		const stderr = err.stderr ? err.stderr.toString() : String(err);
		try {
			unlinkSync(tmpJs);
		} catch {
			/* best effort */
		}
		fail(`syntax error after rewrite — targets left untouched. node --check output:\n${stderr}`);
	}
	try {
		unlinkSync(tmpJs);
	} catch {
		/* best effort */
	}
}

for (const write of writes) {
	if (write.backup && existsSync(write.path)) ensureBackup(write.path);
	writeValidated(write.path, write.content);
}

const verifyDrop = existsSync(dropPath) ? readFileSync(dropPath, "utf8") : "";
if (!verifyDrop.includes(MARKER_PREFIX)) {
	fail(`dropped ${dropPath} is missing marker ${MARKER_PREFIX}`);
}
for (const file of files) {
	const verify = readFileSync(file.path, "utf8");
	const markerCountAfter = countMarker(verify, MARKER);
	if (markerCountAfter !== file.edits.length) {
		fail(`post-patch marker count ${markerCountAfter} ≠ expected ${file.edits.length} in ${file.path}. Restore from ${backupPath(file.path)}.`);
	}
}

writeStateFile({
	status: "patched",
	target: dropPath,
	backup: backupPath(files[0].path),
	versions,
	patchRevision: PATCH_REVISION,
	fingerprintPre: sha256(snapshots.map((file) => file.original).join("\n")),
	fingerprintPost: sha256(files.map((file) => readFileSync(file.path, "utf8")).join("\n")),
});
log(`patched at revision ${PATCH_REVISION}`);
process.exit(0);
