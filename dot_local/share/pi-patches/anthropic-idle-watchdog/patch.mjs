#!/usr/bin/env node
// chezmoi-pi-patch:anthropic-idle-watchdog
//
// Idempotently patches @earendil-works/pi-ai's compiled
// api/anthropic-messages.js to add a per-chunk SSE idle watchdog and forward
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
import { mkdirSync, readFileSync, readdirSync, writeFileSync, copyFileSync, existsSync, renameSync, unlinkSync } from "node:fs";
import { dirname, join } from "node:path";
import { homedir } from "node:os";

// Bump this when patch.mjs's edits change. The marker comment embedded into
// the patched file uses this; a stale marker fails closed rather than
// restoring a shared-file backup over sibling patches.
const PATCH_REVISION = 2;

const PATCH_NAME = "anthropic-idle-watchdog";
const MARKER = `chezmoi-pi-patch:${PATCH_NAME} v${PATCH_REVISION}`;
const BACKUP_SUFFIX = ".orig.chezmoi-pi-patch";
const STATE_DIR = join(homedir(), ".local", "state", "chezmoi-pi-patches");
const STATE_FILE = join(STATE_DIR, `${PATCH_NAME}.json`);

const log = (msg) => console.log(`[pi-patch:${PATCH_NAME}] ${msg}`);
const fail = (msg) => {
	console.error(`[pi-patch:${PATCH_NAME}] ERROR: ${msg}`);
	process.exit(1);
};

const checkOnly = process.argv.includes("--check");
const isolatedPackage = process.env.PI_ANTHROPIC_IDLE_WATCHDOG_PACKAGE;

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
                await options?.onProviderStreamEvent?.(event, model);
                if (event.type === "message_start") {`,
		replace: `            for await (const event of iterateAnthropicEvents(response, options?.signal)) {
                await options?.onProviderStreamEvent?.(event, model);
                // ${MARKER} — surface ping events for heartbeat / progress
                if (event.type === "ping") {
                    stream.push({ type: "ping", partial: output });
                    continue;
                }
                if (event.type === "message_start") {`,
	},
];

// ─── Locate target ─────────────────────────────────────────────────────────
//
// pi-ai was historically published under the @mariozechner scope with the SSE
// provider at dist/providers/anthropic.js. Newer builds (0.80.x) publish under
// @earendil-works, nest pi-ai inside pi-coding-agent's node_modules, and moved
// the streaming code to dist/api/anthropic-messages.js. Probe every known
// layout so the patch survives scope renames and internal refactors.
const SCOPES = ["@earendil-works", "@mariozechner"];
const PI_AI_SUBPATHS = [
	"dist/api/anthropic-messages.js", // 0.80.x+
	"dist/providers/anthropic.js", // legacy
];

function firstExisting(paths) {
	for (const p of paths) {
		if (p && existsSync(p)) return p;
	}
	return null;
}

function locateTarget() {
	if (isolatedPackage) {
		const target = join(isolatedPackage, "node_modules", "@earendil-works", "pi-ai", "dist", "api", "anthropic-messages.js");
		if (!existsSync(target)) fail(`isolated pi-ai target not found: ${target}`);
		return target;
	}
	// We run under the same node that runs pi (chezmoi invokes `node patch.mjs`).
	const requireFromHome = createRequire(join(homedir(), "package.json"));
	const candidates = [];
	for (const scope of SCOPES) {
		for (const sub of PI_AI_SUBPATHS) {
			// 1. pi-ai resolvable directly (hoisted to a top-level node_modules).
			try {
				candidates.push(requireFromHome.resolve(`${scope}/pi-ai/${sub}`));
			} catch {
				/* not hoisted under this scope */
			}
			// 2. pi-ai nested under pi-coding-agent — resolve the parent, walk in.
			try {
				const pcaPkg = requireFromHome.resolve(`${scope}/pi-coding-agent/package.json`);
				candidates.push(join(dirname(pcaPkg), "node_modules", scope, "pi-ai", sub));
			} catch {
				/* pi-coding-agent not under this scope */
			}
		}
	}
	// 3. npm global root fallback, both nesting shapes.
	try {
		const npmRoot = execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim();
		for (const scope of SCOPES) {
			for (const sub of PI_AI_SUBPATHS) {
				candidates.push(join(npmRoot, scope, "pi-coding-agent", "node_modules", scope, "pi-ai", sub));
				candidates.push(join(npmRoot, scope, "pi-ai", sub));
			}
		}
	} catch {
		/* npm not on PATH */
	}
	return firstExisting(candidates);
}

function getInstalledVersions() {
	if (isolatedPackage) {
		return {
			piCodingAgent: JSON.parse(readFileSync(join(isolatedPackage, "package.json"), "utf8")).version,
			piAi: JSON.parse(readFileSync(join(isolatedPackage, "node_modules", "@earendil-works", "pi-ai", "package.json"), "utf8")).version,
			scope: "@earendil-works",
			root: isolatedPackage,
		};
	}
	const versions = { piCodingAgent: null, piAi: null, scope: null };
	const requireFromHome = createRequire(join(homedir(), "package.json"));
	let npmRoot;
	try {
		npmRoot = execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim();
	} catch {
		/* npm not on PATH — home-resolve may still work */
	}
	for (const scope of SCOPES) {
		let pcaPkgPath;
		try {
			pcaPkgPath = requireFromHome.resolve(`${scope}/pi-coding-agent/package.json`);
		} catch {
			if (npmRoot) {
				const c = join(npmRoot, scope, "pi-coding-agent", "package.json");
				if (existsSync(c)) pcaPkgPath = c;
			}
		}
		if (!pcaPkgPath) continue;
		try {
			versions.piCodingAgent = JSON.parse(readFileSync(pcaPkgPath, "utf8")).version;
		} catch {
			/* ignore */
		}
		versions.scope = scope;
		const pcaDir = dirname(pcaPkgPath);
		versions.root = pcaDir;
		const piAiPkgCandidates = [
			join(pcaDir, "node_modules", scope, "pi-ai", "package.json"), // nested
			join(pcaDir, "..", "pi-ai", "package.json"), // hoisted sibling
		];
		for (const c of piAiPkgCandidates) {
			try {
				if (existsSync(c)) {
					versions.piAi = JSON.parse(readFileSync(c, "utf8")).version;
					break;
				}
			} catch {
				/* ignore */
			}
		}
		break;
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

const versions = getInstalledVersions();
const chunks = versions.root && join(versions.root, "dist", "bundle", "chunks");
if (!chunks || !existsSync(chunks)) fail("Pi CLI bundle not found; update this patch for the installed version");
const bundles = readdirSync(chunks).filter((file) => file.endsWith(".js") &&
	readFileSync(join(chunks, file), "utf8").includes("async function*iterateAnthropicEvents(response,signal)"));
if (bundles.length !== 1) fail(`expected one Anthropic CLI bundle, found ${bundles.length}`);
const bundle = join(chunks, bundles[0]);
const bundleEdits = [
	{
		name: "CLI event filter — forward ping",
		find: 'ANTHROPIC_MESSAGE_EVENTS=new Set(["message_start","message_delta","message_stop","content_block_start","content_block_delta","content_block_stop"])',
		replace: `ANTHROPIC_MESSAGE_EVENTS=new Set(["message_start","message_delta","message_stop","content_block_start","content_block_delta","content_block_stop","ping"/* ${MARKER} */])`,
	},
	{
		name: "CLI SSE reader — idle watchdog",
		find: 'if(signal?.aborted)throw new Error("Request was aborted");let{value,done}=await reader.read();',
		replace: EDITS[1].replace,
	},
	{
		name: "CLI stream — provider callback before ping handling",
		find: 'stream2.push({type:"start",partial:output});let blocks=output.content;for await(let event of iterateAnthropicEvents(response,options?.signal))if(await options?.onProviderStreamEvent?.(event,model),event.type==="message_start")',
		replace: `stream2.push({type:"start",partial:output});let blocks=output.content;for await(let event of iterateAnthropicEvents(response,options?.signal))if(await options?.onProviderStreamEvent?.(event,model),event.type==="ping"){/* ${MARKER} */stream2.push({type:"ping",partial:output})}else if(event.type==="message_start")`,
	},
];

main([{ target, edits: EDITS }, { target: bundle, edits: bundleEdits }], versions);

// ─── Patch application ────────────────────────────────────────────────────

function main(files, vers) {
	const prepared = files.map(({ target, edits }) => {
		const original = readFileSync(target, "utf8");
		const markerCount = countOccurrences(original, MARKER);
		if (markerCount > 0) {
			if (markerCount !== edits.length || edits.some((edit) => countOccurrences(original, edit.replace) !== 1)) {
				fail(`patch blocks are incomplete or changed in ${target}; no files were modified`);
			}
			return { target, original, content: original };
		}
		// Shared files may carry sibling patches. Never restore a whole-file backup.
		if (original.includes(`chezmoi-pi-patch:${PATCH_NAME}`)) {
			fail(`stale patch revision in ${target}; expected v${PATCH_REVISION}. No files were modified. Reinstall the current Pi version, then reapply all patches.`);
		}
		let content = original;
		for (const edit of edits) {
			const occurrences = countOccurrences(original, edit.find);
			if (occurrences !== 1) {
				emitDiagnostic(target, original, edit, occurrences);
				fail(`anchor for edit "${edit.name}" found ${occurrences} times (expected 1) in ${target}; update this patch rather than guessing`);
			}
			content = content.replace(edit.find, edit.replace);
		}
		return { target, original, content };
	});
	const changing = prepared.filter((file) => file.content !== file.original);
	if (checkOnly) {
		if (changing.length) fail(`unpatched files at revision ${PATCH_REVISION}: ${changing.map((file) => file.target).join(", ")}`);
		log(`verified SDK and CLI patch blocks at revision ${PATCH_REVISION}`);
		return;
	}
	// Validate all rewritten JavaScript before replacing either runtime surface.
	const temporary = [];
	try {
		for (const file of changing) {
			file.tmp = `${file.target}.${PATCH_NAME}.tmp.js`;
			temporary.push(file.tmp);
			writeFileSync(file.tmp, file.content, "utf8");
			execFileSync(process.execPath, ["--check", file.tmp], { stdio: "pipe" });
		}
		for (const file of changing) {
			const backup = `${file.target}${BACKUP_SUFFIX}`;
			if (!existsSync(backup)) copyFileSync(file.target, backup);
			renameSync(file.tmp, file.target);
			log(`patched ${file.target}`);
		}
	} finally {
		for (const tmp of temporary) if (existsSync(tmp)) unlinkSync(tmp);
	}
	writeStateFile({
		status: changing.length ? "patched" : "already-patched",
		target: files[0].target,
		backup: `${files[0].target}${BACKUP_SUFFIX}`,
		versions: vers,
		targets: prepared.map((file) => ({ target: file.target, sha256: sha256(file.content) })),
	});
	log(`${changing.length ? "patched" : "already patched"} SDK and CLI at revision ${PATCH_REVISION}`);
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
	if (isolatedPackage) return;
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
