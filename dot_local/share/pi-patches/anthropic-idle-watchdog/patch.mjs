#!/usr/bin/env node
// chezmoi-pi-patch:anthropic-idle-watchdog
//
// Idempotently patches @mariozechner/pi-ai's compiled
// providers/anthropic.js to add a per-chunk SSE idle watchdog and forward
// Anthropic ping events through the AssistantMessageEventStream.
//
// See sibling README.md for rationale, failure modes, and resolution.
// Upstream issue: https://github.com/badlogic/pi-mono/issues/3020
//
// Usage:
//   node patch.mjs [--check]
//
//   --check   Verify state without making changes; exit non-zero if the
//             file isn't patched at the current PATCH_REVISION.

import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync, copyFileSync, existsSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { homedir } from "node:os";

// Bump this when patch.mjs's edits change. The marker comment embedded into
// the patched file uses this; a stale marker triggers an automatic
// restore-from-backup + re-apply.
const PATCH_REVISION = 1;

const PATCH_NAME = "anthropic-idle-watchdog";
const MARKER = `chezmoi-pi-patch:${PATCH_NAME} v${PATCH_REVISION}`;
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

// ─── Edit definitions ──────────────────────────────────────────────────────
//
// Each edit is a literal-string replacement. The `find` string MUST appear
// exactly once in the unpatched file; the `replace` string contains the
// MARKER comment so we can detect "already patched" without re-running the
// surgery.
//
// Any change to these strings must come with a PATCH_REVISION bump.

const EDITS = [
	{
		name: "ANTHROPIC_MESSAGE_EVENTS — forward ping",
		find: `const ANTHROPIC_MESSAGE_EVENTS = new Set([
    "message_start",
    "message_delta",
    "message_stop",
    "content_block_start",
    "content_block_delta",
    "content_block_stop",
]);`,
		replace: `const ANTHROPIC_MESSAGE_EVENTS = new Set([
    "message_start",
    "message_delta",
    "message_stop",
    "content_block_start",
    "content_block_delta",
    "content_block_stop",
    "ping", // ${MARKER}
]);`,
	},
	{
		name: "iterateSseMessages — idle watchdog around reader.read()",
		find: `            if (signal?.aborted) {
                throw new Error("Request was aborted");
            }
            const { value, done } = await reader.read();`,
		replace: `            if (signal?.aborted) {
                throw new Error("Request was aborted");
            }
            // ${MARKER} — per-chunk SSE idle watchdog
            const __piPatchIdleMs = Number(process.env.PI_STREAM_IDLE_TIMEOUT_MS);
            const __piPatchTimeoutMs = Number.isFinite(__piPatchIdleMs) ? __piPatchIdleMs : 90000;
            let __piPatchChunk;
            if (__piPatchTimeoutMs > 0) {
                let __piPatchTimer;
                const __piPatchIdle = new Promise((_, reject) => {
                    __piPatchTimer = setTimeout(
                        () => reject(new Error(\`Anthropic SSE idle for \${__piPatchTimeoutMs}ms (chezmoi-pi-patch)\`)),
                        __piPatchTimeoutMs,
                    );
                });
                try {
                    __piPatchChunk = await Promise.race([reader.read(), __piPatchIdle]);
                } catch (__piPatchErr) {
                    try { await reader.cancel(); } catch {}
                    throw __piPatchErr;
                } finally {
                    clearTimeout(__piPatchTimer);
                }
            } else {
                __piPatchChunk = await reader.read();
            }
            const { value, done } = __piPatchChunk;`,
	},
	{
		name: "streamAnthropic — forward ping events to AssistantMessageEventStream",
		find: `            for await (const event of iterateAnthropicEvents(response, options?.signal)) {
                if (event.type === "message_start") {`,
		replace: `            for await (const event of iterateAnthropicEvents(response, options?.signal)) {
                // ${MARKER} — surface ping events for heartbeat / progress
                if (event.type === "ping") {
                    stream.push({ type: "ping", partial: output });
                    continue;
                }
                if (event.type === "message_start") {`,
	},
];

// ─── Locate target ─────────────────────────────────────────────────────────

function locateTarget() {
	// Try via the user's nominal node (the one that runs pi). We're already
	// running under it because chezmoi invokes `node patch.mjs`.
	const requireFromHome = createRequire(join(homedir(), "package.json"));
	let resolved;
	try {
		resolved = requireFromHome.resolve("@mariozechner/pi-ai/dist/providers/anthropic.js");
	} catch {
		// Fall back to npm's global root.
		try {
			const npmRoot = execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim();
			const candidate = join(
				npmRoot,
				"@mariozechner",
				"pi-coding-agent",
				"node_modules",
				"@mariozechner",
				"pi-ai",
				"dist",
				"providers",
				"anthropic.js",
			);
			if (existsSync(candidate)) {
				resolved = candidate;
			}
		} catch {
			/* npm not on PATH */
		}
	}
	if (!resolved || !existsSync(resolved)) {
		return null;
	}
	return resolved;
}

function getInstalledVersions() {
	const versions = { piCodingAgent: null, piAi: null };
	let npmRoot;
	try {
		npmRoot = execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim();
	} catch {
		return versions;
	}
	try {
		const pkg = JSON.parse(
			readFileSync(join(npmRoot, "@mariozechner", "pi-coding-agent", "package.json"), "utf8"),
		);
		versions.piCodingAgent = pkg.version;
	} catch {
		/* ignore */
	}
	try {
		const pkg = JSON.parse(
			readFileSync(
				join(npmRoot, "@mariozechner", "pi-coding-agent", "node_modules", "@mariozechner", "pi-ai", "package.json"),
				"utf8",
			),
		);
		versions.piAi = pkg.version;
	} catch {
		/* ignore */
	}
	return versions;
}

// ─── Main ──────────────────────────────────────────────────────────────────

const target = locateTarget();
if (!target) {
	if (checkOnly) {
		fail("pi-ai not installed; cannot verify patch");
	}
	log("pi-ai not installed — nothing to patch");
	process.exit(0);
}
log(`target: ${target}`);

const original = readFileSync(target, "utf8");
const versions = getInstalledVersions();

// ─── Idempotency: marker check ────────────────────────────────────────────

const markerCount = (original.match(new RegExp(MARKER.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "g")) || []).length;

if (markerCount > 0) {
	// File already carries our marker for this revision.
	if (markerCount !== EDITS.length) {
		warn(
			`marker count (${markerCount}) ≠ expected (${EDITS.length}); file may be partially patched`,
		);
	}
	if (checkOnly) {
		log(`already patched at revision ${PATCH_REVISION}`);
		process.exit(0);
	}
	// Refresh state file in case it was lost (e.g. fresh machine).
	writeStateFile({ status: "already-patched", target, versions });
	log(`already patched at revision ${PATCH_REVISION} — no-op`);
	process.exit(0);
}

// Look for stale marker (different revision) — restore from backup before
// re-patching.
const STALE_MARKER_PREFIX = `chezmoi-pi-patch:${PATCH_NAME}`;
if (original.includes(STALE_MARKER_PREFIX)) {
	if (checkOnly) {
		fail(`stale patch revision present; expected v${PATCH_REVISION}`);
	}
	const backup = `${target}${BACKUP_SUFFIX}`;
	if (!existsSync(backup)) {
		fail(
			`stale patch revision in ${target} but no backup at ${backup} — cannot safely re-patch. Manually reinstall pi-coding-agent and re-run chezmoi apply.`,
		);
	}
	log(`stale patch revision detected; restoring from ${backup}`);
	copyFileSync(backup, target);
	// Re-read from the restored file.
	process.argv.push("--restored");
	main(target, readFileSync(target, "utf8"), versions);
	process.exit(0);
}

if (checkOnly) {
	fail(`file is unpatched at revision ${PATCH_REVISION}`);
}

main(target, original, versions);

// ─── Patch application ────────────────────────────────────────────────────

function main(targetPath, content, vers) {
	// Pre-flight: every anchor must appear exactly once.
	for (const edit of EDITS) {
		const occurrences = countOccurrences(content, edit.find);
		if (occurrences !== 1) {
			emitDiagnostic(targetPath, content, edit, occurrences);
			fail(
				`anchor for edit "${edit.name}" found ${occurrences} times (expected 1) in ${targetPath}. ` +
					`See diagnostic above. Either upstream changed the code shape (update patch.mjs anchors and bump PATCH_REVISION) ` +
					`or upstream merged a real fix (delete this patch — see README §F1).`,
			);
		}
	}

	// Backup once per pi-ai install. If a backup exists from a prior
	// revision, leave it (it captures the truly-unpatched state).
	const backup = `${targetPath}${BACKUP_SUFFIX}`;
	if (!existsSync(backup)) {
		copyFileSync(targetPath, backup);
		log(`backup written: ${backup}`);
	}

	// Apply edits.
	let patched = content;
	for (const edit of EDITS) {
		patched = patched.replace(edit.find, edit.replace);
	}

	// Write atomically: temp file → fsync → rename. Preserve the .js
	// extension so `node --check` can determine module type from the
	// containing package.json ("type": "module").
	const tmp = targetPath.replace(/\.js$/, "") + ".chezmoi-pi-patch.tmp.js";
	writeFileSync(tmp, patched, "utf8");

	// Validate via `node --check`.
	try {
		execFileSync(process.execPath, ["--check", tmp], { stdio: "pipe" });
	} catch (err) {
		const stderr = err.stderr ? err.stderr.toString() : String(err);
		try {
			execFileSync("rm", ["-f", tmp]);
		} catch {
			/* best effort */
		}
		fail(`syntax error after patch application — restored target untouched. node --check output:\n${stderr}`);
	}

	// Atomic replace.
	execFileSync("mv", [tmp, targetPath]);

	// Verify markers landed.
	const verify = readFileSync(targetPath, "utf8");
	const markerCountAfter = (
		verify.match(new RegExp(MARKER.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "g")) || []
	).length;
	if (markerCountAfter !== EDITS.length) {
		fail(
			`post-patch marker count ${markerCountAfter} ≠ expected ${EDITS.length}. ` +
				`Restoring from backup at ${backup}.`,
		);
	}

	writeStateFile({
		status: "patched",
		target: targetPath,
		backup,
		versions: vers,
		patchRevision: PATCH_REVISION,
		fingerprintPre: sha256(content),
		fingerprintPost: sha256(verify),
	});

	log(`patched ${EDITS.length} edits at revision ${PATCH_REVISION} (pi-ai ${vers.piAi}, pi-coding-agent ${vers.piCodingAgent})`);
}

// ─── Helpers ──────────────────────────────────────────────────────────────

function countOccurrences(haystack, needle) {
	if (needle.length === 0) return 0;
	let n = 0;
	let i = 0;
	while ((i = haystack.indexOf(needle, i)) !== -1) {
		n += 1;
		i += needle.length;
	}
	return n;
}

function sha256(s) {
	return createHash("sha256").update(s).digest("hex");
}

function emitDiagnostic(targetPath, content, edit, occurrences) {
	console.error("");
	console.error(`──────── pi-patch diagnostic: ${edit.name} ────────`);
	console.error(`Target:       ${targetPath}`);
	console.error(`Occurrences:  ${occurrences} (expected 1)`);
	console.error(`Expected anchor (sha256: ${sha256(edit.find)}):`);
	console.error(indent(edit.find));
	if (occurrences === 0) {
		// Try to find the closest matching prefix line for orientation.
		const firstLine = edit.find.split("\n")[0];
		const lineIdx = content.split("\n").findIndex((l) => l.includes(firstLine.trim()));
		if (lineIdx >= 0) {
			const start = Math.max(0, lineIdx - 2);
			const end = Math.min(content.split("\n").length, lineIdx + 8);
			console.error(`Closest match in current file (lines ${start + 1}-${end}):`);
			console.error(indent(content.split("\n").slice(start, end).join("\n")));
		}
	}
	console.error("──────────────────────────────────────────────");
	console.error("");
}

function indent(s) {
	return s
		.split("\n")
		.map((l) => `  | ${l}`)
		.join("\n");
}

function writeStateFile(payload) {
	mkdirSync(STATE_DIR, { recursive: true });
	const state = {
		patchName: PATCH_NAME,
		patchRevision: PATCH_REVISION,
		appliedAt: new Date().toISOString(),
		nodeVersion: process.version,
		upstreamIssue: "https://github.com/badlogic/pi-mono/issues/3020",
		...payload,
	};
	writeFileSync(STATE_FILE, JSON.stringify(state, null, 2) + "\n", "utf8");
}
