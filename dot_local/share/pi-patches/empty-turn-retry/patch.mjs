#!/usr/bin/env node
// chezmoi-pi-patch:empty-turn-retry
//
// Surfaces degenerate empty assistant turns as retryable provider errors
// inside pi-ai's anthropic-messages stream function. Gateway models (GLM-5.3
// via boost-litellm) sometimes sample EOS immediately: the response carries
// an empty text block (or thinking-only content) with rawStopReason
// "end_turn" and 0 output tokens. pi's agent loop continues whenever a
// response contains tool-call blocks, but treats stop-with-no-content as a
// legitimate finish and ends the turn silently — the user sees the turn die
// right after a tool call with no error and has to type "continue".
//
// The fix throws a "Provider returned error: ..." message for a stop-reason
// turn with no tool calls and no non-empty text. That wording matches
// pi-ai's RETRYABLE_PROVIDER_ERROR_PATTERN (and no OVERFLOW_PATTERN), so
// agent-session auto-retries the turn (default budget: 3 retries, 2s base
// backoff) instead of ending it. Errored assistant messages are excluded
// from the LLM context (pi-agent-core context.js isContextMessage), so the
// retry starts clean. Thinking-only turns count as degenerate: a final
// assistant turn must carry text or a tool call to be useful.
//
// Applied on ALL profiles (no profile gate). See README.md.

import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync, copyFileSync, existsSync, unlinkSync } from "node:fs";
import { dirname, join } from "node:path";
import { homedir } from "node:os";

const PATCH_REVISION = 1;

const PATCH_NAME = "empty-turn-retry";
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

const EDITS = [
	{
		name: "stream — surface empty end_turn turns as retryable provider errors",
		find: `            if (output.stopReason === "pending") {
                throw new Error("Anthropic stream ended without a stop reason");
            }
            if (output.stopReason === "aborted" || output.stopReason === "error") {
                throw new Error(output.errorMessage || "An unknown error occurred");
            }`,
		replace: `            if (output.stopReason === "pending") {
                throw new Error("Anthropic stream ended without a stop reason");
            }
            if (output.stopReason === "aborted" || output.stopReason === "error") {
                throw new Error(output.errorMessage || "An unknown error occurred");
            }
            // ${MARKER} — a stop-reason turn with no tool calls and no
            // non-empty text is a degenerate empty turn (premature EOS:
            // empty text block or thinking-only content). The agent loop
            // would end the turn silently; surface it as a retryable
            // provider error instead. "provider returned error" matches
            // RETRYABLE_PROVIDER_ERROR_PATTERN and no OVERFLOW_PATTERN
            // matches, so this routes to auto-retry, not compaction.
            if (
                output.stopReason === "stop" &&
                !output.content.some(
                    (block) =>
                        block.type === "toolCall" ||
                        (block.type === "text" &&
                            typeof block.text === "string" &&
                            block.text.trim() !== ""),
                )
            ) {
                throw new Error(
                    "Provider returned error: empty assistant turn (stop_reason=end_turn, no text and no tool calls) - likely premature EOS",
                );
            }`,
	},
];

// pi-ai is nested inside pi-coding-agent's node_modules on current builds
// (0.80.x+); the streaming code lives in dist/api/anthropic-messages.js.
// Older layouts hoisted pi-ai to a top-level node_modules — probe both.
function locateTarget() {
	const requireFromHome = createRequire(join(homedir(), "package.json"));
	const candidates = [];
	// 1. pi-coding-agent resolvable — walk into its nested pi-ai.
	try {
		const pcaPkg = requireFromHome.resolve("@earendil-works/pi-coding-agent/package.json");
		candidates.push(join(dirname(pcaPkg), "node_modules", "@earendil-works", "pi-ai", "dist", "api", "anthropic-messages.js"));
	} catch {
		/* pi-coding-agent not resolvable from home */
	}
	// 2. pi-ai hoisted directly.
	try {
		candidates.push(requireFromHome.resolve("@earendil-works/pi-ai/dist/api/anthropic-messages.js"));
	} catch {
		/* not hoisted */
	}
	// 3. npm global root fallback, both nesting shapes.
	try {
		const npmRoot = execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim();
		candidates.push(join(npmRoot, "@earendil-works", "pi-coding-agent", "node_modules", "@earendil-works", "pi-ai", "dist", "api", "anthropic-messages.js"));
		candidates.push(join(npmRoot, "@earendil-works", "pi-ai", "dist", "api", "anthropic-messages.js"));
	} catch {
		/* npm not on PATH */
	}
	for (const p of candidates) {
		if (p && existsSync(p)) return p;
	}
	return null;
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
	if (checkOnly) fail("pi-ai not installed; cannot verify patch");
	log("pi-ai not installed — nothing to patch");
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
				`Upstream likely changed the anthropic stream() terminal-check shape — update patch.mjs anchors and bump PATCH_REVISION, ` +
				`or upstream started rejecting empty end_turn turns itself (delete this patch — see README).`,
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
