#!/usr/bin/env node
// chezmoi-pi-patch:custom-message-marker
//
// Wraps extension-injected `custom` messages (hindsight memories, goals, etc.)
// in <injected-context> ... </injected-context> tags inside pi-core's
// convertToLlm(). pi flattens custom messages to role:"user" and drops the
// customType, so a turn-oriented provider adapter (e.g. the cursor provider,
// whose upstream is user-turn oriented) cannot tell injected context apart
// from a real user turn — it mistakes the trailing injected block for the
// current prompt and demotes the real prompt into history. This marker
// restores that lost signal structurally: the cursor fork
// (cartwmic/pi-cursor, context-normalize.ts) treats <injected-context>
// blocks as side-channel context and folds them into the system prompt,
// while genuine consecutive user messages (interrupts) stay untouched.
// Stateless providers simply see the bracketed text.
//
// Applied on ALL profiles (no profile gate). See README.md.

import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, readdirSync, writeFileSync, copyFileSync, existsSync, unlinkSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";
import { piCodingAgentRoot } from "../pi-root.mjs";

const PATCH_REVISION = 1;

const PATCH_NAME = "custom-message-marker";
const MARKER = `chezmoi-pi-patch:${PATCH_NAME} v${PATCH_REVISION}`;
const MARKER_PREFIX = `chezmoi-pi-patch:${PATCH_NAME}`; // any revision
const BACKUP_SUFFIX = ".orig.chezmoi-pi-patch";
const STATE_DIR = join(homedir(), ".local", "state", "chezmoi-pi-patches");
const STATE_FILE = join(STATE_DIR, `${PATCH_NAME}.json`);

const log = (msg) => console.log(`[pi-patch:${PATCH_NAME}] ${msg}`);
const warn = (msg) => console.warn(`[pi-patch:${PATCH_NAME}] WARN: ${msg}`);
const fail = (msg) => {
	console.error(`[pi-patch:${PATCH_NAME}] ERROR: ${msg}`);
	process.exit(1);
};

const checkOnly = process.argv.includes("--check");

// Keep the open tag in sync with the <injected-context> marker in
// SIDE_CHANNEL_BLOCK_START / isContextModeSideChannelText in the
// cartwmic/pi-cursor fork's src/stream/context-normalize.ts.
const SDK_EDITS = [
	{
		name: "convertToLlm — wrap custom-injected content in <injected-context> tags",
		find: `                const content = typeof m.content === "string" ? [{ type: "text", text: m.content }] : m.content;`,
		replace: `                // ${MARKER} — wrap extension-injected context so stateful
                // provider adapters can distinguish it from real user turns.
                const __injectedInner = typeof m.content === "string" ? [{ type: "text", text: m.content }] : (m.content ?? []);
                const content = [{ type: "text", text: "<injected-context>\\n" }, ...__injectedInner, { type: "text", text: "\\n</injected-context>" }];`,
	},
];
// Same edit against the minified CLI bundle.
const BUNDLE_EDITS = [
	{
		name: "bundle convertToLlm — wrap custom-injected content in <injected-context> tags",
		find: `case"custom":return{role:"user",content:typeof m.content=="string"?[{type:"text",text:m.content}]:m.content,timestamp:m.timestamp};`,
		replace: `case"custom":/* ${MARKER} */return{role:"user",content:[{type:"text",text:"<injected-context>\\n"},...(typeof m.content=="string"?[{type:"text",text:m.content}]:m.content??[]),{type:"text",text:"\\n</injected-context>"}],timestamp:m.timestamp};`,
	},
];
const NOT_INSTALLED = "pi-coding-agent not installed";

// The `pi` CLI loads dist/bundle/chunks, not dist/core or pi-ai/dist. Find the
// one chunk that holds convertToLlm.
function locateBundleChunk(pca) {
	const dir = join(pca, "dist", "bundle", "chunks");
	if (!existsSync(dir)) return null;
	const needle = "function convertToLlm(messages){";
	const matches = readdirSync(dir).filter((f) => f.endsWith(".js") && !f.includes(".chezmoi-pi-patch") && readFileSync(join(dir, f), "utf8").includes(needle));
	if (matches.length !== 1) fail(`expected one bundle chunk containing convertToLlm, found ${matches.length}; update this patch for the installed Pi version`);
	return join(dir, matches[0]);
}

// Returns [{ path, edits }]: the SDK file (if present) and the CLI bundle chunk.
function locateTargets() {
	const pca = piCodingAgentRoot();
	if (!pca) return [];
	const targets = [];
	const sdk = join(pca, "dist", "core", "messages.js");
	if (existsSync(sdk)) targets.push({ path: sdk, edits: SDK_EDITS });
	const chunk = locateBundleChunk(pca);
	if (chunk) targets.push({ path: chunk, edits: BUNDLE_EDITS });
	return targets;
}

function getInstalledVersion() {
	try {
		const pkg = JSON.parse(readFileSync(join(piCodingAgentRoot(), "package.json"), "utf8"));
		return pkg.version;
	} catch {
		return null;
	}
}

const sha256 = (s) => createHash("sha256").update(s).digest("hex");
const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const countMarker = (s, marker) => (s.match(new RegExp(escapeRe(marker), "g")) || []).length;

function countOccurrences(haystack, needle) {
	let count = 0;
	let idx = haystack.indexOf(needle);
	while (idx !== -1) {
		count += 1;
		idx = haystack.indexOf(needle, idx + needle.length);
	}
	return count;
}

function writeStateFile(payload) {
	try {
		mkdirSync(STATE_DIR, { recursive: true });
		writeFileSync(STATE_FILE, JSON.stringify({ ...payload, patchName: PATCH_NAME, when: new Date().toISOString() }, null, 2));
	} catch {
	}
}

function writeValidated(targetPath, content) {
	const tmp = targetPath.replace(/\.js$/, "") + ".chezmoi-pi-patch.tmp.js";
	writeFileSync(tmp, content, "utf8");
	try {
		execFileSync(process.execPath, ["--check", tmp], { stdio: "pipe" });
	} catch (err) {
		const stderr = err.stderr ? err.stderr.toString() : String(err);
		try { unlinkSync(tmp); } catch {}
		fail(`syntax error after rewrite — target left untouched. node --check output:\n${stderr}`);
	}
	execFileSync("mv", [tmp, targetPath]);
}

const targets = locateTargets();
if (targets.length === 0) {
	if (checkOnly) fail(NOT_INSTALLED + "; cannot verify patch");
	log(NOT_INSTALLED + " — nothing to patch");
	process.exit(0);
}
const version = getInstalledVersion();
const results = [];

for (const { path: target, edits } of targets) {
	log(`target: ${target}`);
	const original = readFileSync(target, "utf8");
	const markerCount = countMarker(original, MARKER);
	if (markerCount > 0) {
		if (markerCount !== edits.length) warn(`marker count (${markerCount}) ≠ expected (${edits.length}) in ${target}; file may be partially patched`);
		results.push({ target, status: "already-patched" });
		continue;
	}
	let content = original;
	const backup = `${target}${BACKUP_SUFFIX}`;
	if (original.includes(MARKER_PREFIX)) {
		if (checkOnly) fail(`stale patch revision present in ${target}; expected v${PATCH_REVISION}`);
		if (!existsSync(backup)) {
			fail(`stale patch revision in ${target} but no backup at ${backup} — cannot safely re-patch. Reinstall Pi and re-run chezmoi apply.`);
		}
		log(`stale patch revision detected; restoring from ${backup}`);
		copyFileSync(backup, target);
		content = readFileSync(target, "utf8");
	}
	if (checkOnly) fail(`${target} is unpatched at revision ${PATCH_REVISION}`);
	for (const edit of edits) {
		const occurrences = countOccurrences(content, edit.find);
		if (occurrences !== 1) {
			fail(`anchor for edit "${edit.name}" found ${occurrences} times (expected 1) in ${target}. Upstream likely changed the convertToLlm() custom-case shape — update patch.mjs anchors and bump PATCH_REVISION, or upstream started preserving customType through the LLM boundary (delete this patch — see README).`);
		}
	}
	if (!existsSync(backup)) {
		copyFileSync(target, backup);
		log(`backup written: ${backup}`);
	}
	let patched = content;
	for (const edit of edits) patched = patched.replace(edit.find, edit.replace);
	writeValidated(target, patched);
	const verify = readFileSync(target, "utf8");
	if (countMarker(verify, MARKER) !== edits.length) {
		fail(`post-patch marker count ≠ expected ${edits.length} in ${target}. Restore from backup at ${backup}.`);
	}
	results.push({ target, backup, status: "patched", fingerprintPre: sha256(original), fingerprintPost: sha256(verify) });
}

if (checkOnly) {
	log(`verified ${targets.length} target(s) at revision ${PATCH_REVISION}`);
	process.exit(0);
}
const anyPatched = results.some((r) => r.status === "patched");
writeStateFile({ status: anyPatched ? "patched" : "already-patched", target: targets[0].path, targets: results, version, patchRevision: PATCH_REVISION });
log(anyPatched ? `patched at revision ${PATCH_REVISION}` : `already patched at revision ${PATCH_REVISION} — no-op`);
process.exit(0);
