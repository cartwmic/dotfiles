#!/usr/bin/env node
// chezmoi-pi-patch:hide-nonbridge-claude-models
//
// Idempotently patches @earendil-works/pi-coding-agent's compiled
// core/model-registry.js so that ModelRegistry.getAvailable() additionally
// hides every Claude-family model (id matches /claude/i) whose provider is
// NOT "claude-bridge". getAvailable() is the single chokepoint used by both
// the interactive model picker and `pi --list-models`, so this removes the
// non-bridge Claude models from the user-facing model list WITHOUT touching
// provider auth — the anthropic OAuth token stays configured, so the native
// Anthropic web_search/web_fetch tools and pi-sub-bar keep working.
//
// PROFILE GATE: this patch only applies on the chezmoi `personal` profile.
// The templated wrapper run_onchange_apply_pi_patches.sh.tmpl exports
// PI_CHEZMOI_PROFILE={{ .profile }} before running the apply loop. When that
// value is not "personal" (including unset, e.g. a manual run), this patch
// does nothing — and if a previous run applied it, it restores the original
// file from backup so the install returns to stock.
//
// See sibling README.md for rationale, failure modes, and removal.
//
// Usage:
//   node patch.mjs [--check]
//
//   --check   Verify state without making changes; exit non-zero if the
//             install is not in the desired state for the active profile.

import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync, copyFileSync, existsSync, unlinkSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";

// Bump when the EDITS strings change. The embedded marker uses this; a stale
// marker (different revision) triggers restore-from-backup before re-apply.
const PATCH_REVISION = 2;

const PATCH_NAME = "hide-nonbridge-claude-models";
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
const profile = process.env.PI_CHEZMOI_PROFILE ?? "";
const wantPatched = profile === "personal";

// ─── Edit definitions ──────────────────────────────────────────────────────
//
// Single literal-string replacement. `find` MUST appear exactly once in the
// unpatched file. `replace` carries the MARKER so we can detect "already
// patched" and reverse the edit. Any change here requires a PATCH_REVISION bump.

// v0.80.x moved availability computation from ModelRegistry.getAvailable()
// (model-registry.js) into ModelRuntime (model-runtime.js). ModelRegistry is
// now a facade over runtime.getAvailableSnapshot(). We filter every site that
// produces/returns the available list: the two snapshot builders plus the
// provider-specific bypass in getAvailable(providerId).
const EDITS = [
	{
		name: "updateModelSnapshot — hide non-claude-bridge Claude models",
		find: `            available: all.filter((model) => this.snapshot.configuredProviders.has(model.provider)),`,
		replace: `            // ${MARKER} — hide Claude models from every provider except
            // claude-bridge; auth is intentionally preserved so the anthropic
            // token still powers web_search/web_fetch + sub-bar.
            available: all.filter((model) => this.snapshot.configuredProviders.has(model.provider)
                && !(/claude/i.test(model.id) && model.provider !== "claude-bridge")),`,
	},
	{
		name: "runAvailabilityRefresh — hide non-claude-bridge Claude models",
		find: `            available: [...available],`,
		replace: `            // ${MARKER} — hide Claude models from every provider except claude-bridge.
            available: available.filter((model) => !(/claude/i.test(model.id) && model.provider !== "claude-bridge")),`,
	},
	{
		name: "getAvailable(providerId) bypass — hide non-claude-bridge Claude models",
		find: `                return await this.models.getAvailable(providerId);`,
		replace: `                // ${MARKER} — hide Claude models from every provider except claude-bridge.
                return (await this.models.getAvailable(providerId)).filter((model) => !(/claude/i.test(model.id) && model.provider !== "claude-bridge"));`,
	},
];

// ─── Helpers ───────────────────────────────────────────────────────────────

function locateTarget() {
	const requireFromHome = createRequire(join(homedir(), "package.json"));
	let resolved;
	try {
		resolved = requireFromHome.resolve("@earendil-works/pi-coding-agent/dist/core/model-runtime.js");
	} catch {
		try {
			const npmRoot = execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim();
			const candidate = join(
				npmRoot,
				"@earendil-works",
				"pi-coding-agent",
				"dist",
				"core",
				"model-runtime.js",
			);
			if (existsSync(candidate)) resolved = candidate;
		} catch {
			/* npm not on PATH */
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
		/* best-effort */
	}
}

// Validate + atomically replace target with `content`.
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

// ─── Locate ────────────────────────────────────────────────────────────────

const target = locateTarget();
if (!target) {
	if (checkOnly) fail("pi-coding-agent not installed; cannot verify patch");
	log("pi-coding-agent not installed — nothing to patch");
	process.exit(0);
}
log(`profile=${profile || "(unset)"} target: ${target}`);

const original = readFileSync(target, "utf8");
const markerCount = countMarker(original, MARKER);
const hasAnyMarker = original.includes(MARKER_PREFIX);

// ─── Gate: profile is NOT personal → desired state is UNPATCHED ────────────

if (!wantPatched) {
	if (checkOnly) {
		if (hasAnyMarker) fail(`profile '${profile || "(unset)"}' ≠ personal but target is patched`);
		log("profile ≠ personal; target unpatched as expected");
		process.exit(0);
	}
	if (!hasAnyMarker) {
		log("profile ≠ personal; nothing to do");
		process.exit(0);
	}
	// Un-patch: prefer restoring the byte-exact backup; fall back to reversing
	// the current-revision edits.
	const backup = `${target}${BACKUP_SUFFIX}`;
	if (existsSync(backup)) {
		copyFileSync(backup, target);
		log(`profile ≠ personal; restored original from ${backup} (un-patched)`);
	} else if (markerCount > 0) {
		let reverted = original;
		for (const edit of EDITS) reverted = reverted.replace(edit.replace, edit.find);
		if (reverted.includes(MARKER_PREFIX)) {
			fail(`profile ≠ personal and no backup at ${backup}; reverse-edit failed. Reinstall pi-coding-agent.`);
		}
		writeValidated(target, reverted);
		log("profile ≠ personal; reversed current-revision edits (un-patched)");
	} else {
		fail(`profile ≠ personal; stale marker present but no backup at ${backup}. Reinstall pi-coding-agent.`);
	}
	writeStateFile({ status: "unpatched", target, reason: `profile=${profile || "(unset)"}` });
	process.exit(0);
}

// ─── Gate: profile IS personal → desired state is PATCHED ──────────────────

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

// Stale marker (different revision) → restore from backup before re-patching.
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

// ─── Apply ─────────────────────────────────────────────────────────────────

for (const edit of EDITS) {
	const occurrences = countOccurrences(content, edit.find);
	if (occurrences !== 1) {
		fail(
			`anchor for edit "${edit.name}" found ${occurrences} times (expected 1) in ${target}. ` +
				`Upstream likely changed the getAvailable() shape — update patch.mjs anchors and bump PATCH_REVISION, ` +
				`or upstream added a native model-hide setting (delete this patch — see README).`,
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
