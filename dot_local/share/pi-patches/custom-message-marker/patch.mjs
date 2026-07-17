#!/usr/bin/env node
// chezmoi-pi-patch:custom-message-marker
//
// Wraps extension-injected `custom` messages (hindsight memories, goals, etc.)
// in <injected-context> ... </injected-context> tags inside pi-core's
// convertToLlm(). pi flattens custom messages to role:"user" and drops the
// customType, so a stateful provider adapter (e.g. pi-cursor-provider, whose
// upstream requires strict user->assistant alternation) cannot tell injected
// context apart from a real user turn — it mistakes the trailing injected block
// for the current prompt and demotes the real prompt into history. This marker
// restores that lost signal structurally: the cursor fork coalesces any
// <injected-context>-wrapped trailing user message into the preceding real
// turn, while genuine consecutive user messages (interrupts) stay untouched.
// Stateless providers simply see the bracketed text.
//
// Applied on ALL profiles (no profile gate). See README.md.

import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync, copyFileSync, existsSync, unlinkSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";

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

// Keep the open tag in sync with INJECTED_CONTEXT_OPEN_TAG in the
// pi-cursor-provider fork's proxy.ts.
const EDITS = [
	{
		name: "convertToLlm — wrap custom-injected content in <injected-context> tags",
		find: `                const content = typeof m.content === "string" ? [{ type: "text", text: m.content }] : m.content;`,
		replace: `                // ${MARKER} — wrap extension-injected context so stateful
                // provider adapters can distinguish it from real user turns.
                const __injectedInner = typeof m.content === "string" ? [{ type: "text", text: m.content }] : (m.content ?? []);
                const content = [{ type: "text", text: "<injected-context>\\n" }, ...__injectedInner, { type: "text", text: "\\n</injected-context>" }];`,
	},
];

function locateTarget() {
	const requireFromHome = createRequire(join(homedir(), "package.json"));
	let resolved;
	try {
		resolved = requireFromHome.resolve("@earendil-works/pi-coding-agent/dist/core/messages.js");
	} catch {
		try {
			const npmRoot = execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim();
			const candidate = join(npmRoot, "@earendil-works", "pi-coding-agent", "dist", "core", "messages.js");
			if (existsSync(candidate)) resolved = candidate;
		} catch {
		}
	}
	if (!resolved || !existsSync(resolved)) return null;
	return resolved;
}

function getInstalledVersion() {
	try {
		const npmRoot = execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim();
		const pkg = JSON.parse(
			readFileSync(join(npmRoot, "@earendil-works", "pi-coding-agent", "package.json"), "utf8"),
		);
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

const target = locateTarget();
if (!target) {
	if (checkOnly) fail("pi-coding-agent not installed; cannot verify patch");
	log("pi-coding-agent not installed — nothing to patch");
	process.exit(0);
}
log(`target: ${target}`);

const original = readFileSync(target, "utf8");
const markerCount = countMarker(original, MARKER);
const hasAnyMarker = original.includes(MARKER_PREFIX);
const version = getInstalledVersion();

if (markerCount > 0) {
	if (markerCount !== EDITS.length) warn(`marker count (${markerCount}) ≠ expected (${EDITS.length}); file may be partially patched`);
	if (checkOnly) {
		log(`already patched at revision ${PATCH_REVISION}`);
		process.exit(0);
	}
	writeStateFile({ status: "already-patched", target, version, patchRevision: PATCH_REVISION });
	log(`already patched at revision ${PATCH_REVISION} — no-op`);
	process.exit(0);
}

let content = original;
if (hasAnyMarker) {
	if (checkOnly) fail(`stale patch revision present; expected v${PATCH_REVISION}`);
	const backup = `${target}${BACKUP_SUFFIX}`;
	if (!existsSync(backup)) {
		fail(`stale patch revision in ${target} but no backup at ${backup} — cannot safely re-patch. Reinstall pi-coding-agent and re-run chezmoi apply.`);
	}
	log(`stale patch revision detected; restoring from ${backup}`);
	copyFileSync(backup, target);
	content = readFileSync(target, "utf8");
}

if (checkOnly) fail(`file is unpatched at revision ${PATCH_REVISION}`);

for (const edit of EDITS) {
	const occurrences = countOccurrences(content, edit.find);
	if (occurrences !== 1) {
		fail(
			`anchor for edit "${edit.name}" found ${occurrences} times (expected 1) in ${target}. ` +
				`Upstream likely changed the convertToLlm() custom-case shape — update patch.mjs anchors and bump PATCH_REVISION, ` +
				`or upstream started preserving customType through the LLM boundary (delete this patch — see README).`,
		);
	}
}

const backup = `${target}${BACKUP_SUFFIX}`;
if (!existsSync(backup)) {
	copyFileSync(target, backup);
	log(`backup written: ${backup}`);
}

let patched = content;
for (const edit of EDITS) patched = patched.replace(edit.find, edit.replace);

writeValidated(target, patched);

const verify = readFileSync(target, "utf8");
const markerCountAfter = countMarker(verify, MARKER);
if (markerCountAfter !== EDITS.length) {
	fail(`post-patch marker count ${markerCountAfter} ≠ expected ${EDITS.length}. Restore from backup at ${backup}.`);
}

writeStateFile({
	status: "patched",
	target,
	backup,
	version,
	patchRevision: PATCH_REVISION,
	fingerprintPre: sha256(original),
	fingerprintPost: sha256(verify),
});
log(`patched at revision ${PATCH_REVISION}`);
process.exit(0);
