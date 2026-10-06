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

const PATCH_REVISION = 2;

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
const SDK_MESSAGES_EDITS = [
	{
		name: "convertToLlm - wrap custom-injected content in <injected-context> tags; pass promptIntent turns through unwrapped",
		finds: [
			// Original (unpatched) form - matches after backup restore on a fresh install.
			"                const content = typeof m.content === \"string\" ? [{ type: \"text\", text: m.content }] : m.content;",
		],
		replace: "                // chezmoi-pi-patch:custom-message-marker v2 - wrap extension-injected context so\n                // stateful provider adapters can distinguish it from real user turns. Messages\n                // created as turn prompts (promptIntent, set by sendCustomMessage for\n                // triggerTurn/steer deliveries) are the task, not injected context, and pass\n                // through unwrapped.\n                const __injectedInner = typeof m.content === \"string\" ? [{ type: \"text\", text: m.content }] : (m.content ?? []);\n                if (m.promptIntent === true) {\n                    return { role: \"user\", content: __injectedInner, timestamp: m.timestamp };\n                }\n                const content = [{ type: \"text\", text: \"<injected-context>\\n\" }, ...__injectedInner, { type: \"text\", text: \"\\n</injected-context>\" }];",
	},
];

const SDK_AGENT_SESSION_EDITS = [
	{
		name: "sendCustomMessage - persist promptIntent (delivery intent) on the custom message",
		finds: ["        const appMessage = {\n            role: \"custom\",\n            customType: message.customType,\n            // Untyped extensions can pass null/missing content; normalize at ingestion.\n            content: message.content ?? [],\n            display: message.display,\n            details: message.details,\n            timestamp: Date.now(),\n        };"],
		replace: "        const appMessage = {\n            role: \"custom\",\n            customType: message.customType,\n            // Untyped extensions can pass null/missing content; normalize at ingestion.\n            content: message.content ?? [],\n            display: message.display,\n            details: message.details,\n            timestamp: Date.now(),\n            // chezmoi-pi-patch:custom-message-marker v2 - persist the delivery intent so\n            // convertToLlm can tell turn prompts (unwrapped) from injected context (wrapped).\n            // Computed to match the delivery branch selected below.\n            promptIntent: options?.deliverAs === \"nextTurn\"\n                ? false\n                : this.isStreaming && !this._isEmittingAgentSettled\n                    ? options?.triggerTurn !== false\n                    : options?.triggerTurn === true,\n        };",
	},
];
// Same edit against the minified CLI bundle.
// Bundle edits: the convertToLlm edit accepts BOTH the original minified form (fresh
// install, after backup restore) and the v1-patched form (transform in place - the chunk
// is shared with settlement-abort/headless-drain/prompt-start-race, so restoring it from
// backup would silently drop their edits).
const BUNDLE_CONVERT_EDITS = [
	{
		name: "bundle convertToLlm - wrap custom-injected content; pass promptIntent turns through unwrapped",
		finds: [
			// Original (unpatched) minified form.
			"case\"custom\":return{role:\"user\",content:typeof m.content==\"string\"?[{type:\"text\",text:m.content}]:m.content,timestamp:m.timestamp};",
			// v1-patched form - transformed in place; the chunk is shared with other patches,
			// so v2 never restores it from backup.
			"case\"custom\":/* chezmoi-pi-patch:custom-message-marker v1 */return{role:\"user\",content:[{type:\"text\",text:\"<injected-context>\\n\"},...(typeof m.content==\"string\"?[{type:\"text\",text:m.content}]:m.content??[]),{type:\"text\",text:\"\\n</injected-context>\"}],timestamp:m.timestamp};",
		],
		replace: "case\"custom\":/* chezmoi-pi-patch:custom-message-marker v2 */if(m.promptIntent===!0)return{role:\"user\",content:typeof m.content==\"string\"?[{type:\"text\",text:m.content}]:m.content??[],timestamp:m.timestamp};return{role:\"user\",content:[{type:\"text\",text:\"<injected-context>\\n\"},...(typeof m.content==\"string\"?[{type:\"text\",text:m.content}]:m.content??[]),{type:\"text\",text:\"\\n</injected-context>\"}],timestamp:m.timestamp};",
	},
];
const BUNDLE_SEND_EDITS = [
	{
		name: "sendCustomMessage - persist promptIntent on the appMessage",
		finds: ["let appMessage={role:\"custom\",customType:message.customType,content:message.content??[],display:message.display,details:message.details,timestamp:Date.now()};"],
		replace: "let appMessage={role:\"custom\",customType:message.customType,content:message.content??[],display:message.display,details:message.details,timestamp:Date.now(),/* chezmoi-pi-patch:custom-message-marker v2 */promptIntent:options?.deliverAs===\"nextTurn\"?!1:this.isStreaming&&!this._isEmittingAgentSettled?options?.triggerTurn!==!1:options?.triggerTurn===!0};",
	},
];
const NOT_INSTALLED = "pi-coding-agent not installed";

// The `pi` CLI loads dist/bundle/chunks, not dist/core or pi-ai/dist. Find the
// one chunk that holds convertToLlm (the sendCustomMessage edit lives in the
// same chunk).
function locateBundleChunk(pca) {
	const dir = join(pca, "dist", "bundle", "chunks");
	if (!existsSync(dir)) return null;
	const needles = ["function convertToLlm(messages){", "sendCustomMessage(message,options){"];
	const found = new Map();
	for (const f of readdirSync(dir)) {
		if (!f.endsWith(".js") || f.includes(".chezmoi-pi-patch")) continue;
		const text = readFileSync(join(dir, f), "utf8");
		for (const needle of needles) if (text.includes(needle)) found.set(f, true);
	}
	if (found.size === 0) return null;
	if (found.size !== 1) fail(`expected one bundle chunk holding convertToLlm/sendCustomMessage, found ${found.size}; update this patch for the installed Pi version`);
	return join(dir, [...found.keys()][0]);
}

// Returns [{ path, edits, restore }]: the SDK files (if present) and the CLI bundle chunk.
// restore=true means the target is solely owned by this patch (backup restore is safe).
// restore=false means the file is shared with other patches - v2 never restores it from
// backup (that would silently drop their edits); a stale revision is transformed in place
// by the alternative anchors instead.
function locateTargets() {
	const pca = piCodingAgentRoot();
	if (!pca) return [];
	const targets = [];
	const sdk = join(pca, "dist", "core", "messages.js");
	if (existsSync(sdk)) targets.push({ path: sdk, edits: SDK_MESSAGES_EDITS, restore: true });
	const sdkAgent = join(pca, "dist", "core", "agent-session.js");
	if (existsSync(sdkAgent)) targets.push({ path: sdkAgent, edits: SDK_AGENT_SESSION_EDITS, restore: false });
	const chunk = locateBundleChunk(pca);
	if (chunk) targets.push({ path: chunk, edits: [...BUNDLE_CONVERT_EDITS, ...BUNDLE_SEND_EDITS], restore: false });
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

for (const { path: target, edits, restore } of targets) {
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
		// An older revision of THIS patch is present. For solely-owned targets (messages.js)
		// backup restore is safe. Shared targets (agent-session.js, the bundle chunk) are also
		// patched by other chezmoi patches, so restoring would silently drop their edits —
		// those are transformed in place by the alternative anchors below instead.
		if (checkOnly) fail(`stale patch revision present in ${target}; expected v${PATCH_REVISION}`);
		if (restore) {
			if (!existsSync(backup)) {
				fail(`stale patch revision in ${target} but no backup at ${backup} — cannot safely re-patch. Reinstall Pi and re-run chezmoi apply.`);
			}
			log(`stale patch revision detected; restoring from ${backup}`);
			copyFileSync(backup, target);
			content = readFileSync(target, "utf8");
		}
	}
	if (checkOnly) fail(`${target} is unpatched at revision ${PATCH_REVISION}`);
	for (const edit of edits) {
		// Alternative anchors: exactly one candidate form must match (original or v1-patched).
		const matched = (edit.finds || [edit.find]).filter((f) => countOccurrences(content, f) === 1);
		if (matched.length !== 1) {
			fail(`anchor for edit "${edit.name}" matched ${matched.length} of ${edit.finds ? edit.finds.length : 1} candidate forms in ${target} (exactly 1 expected). Upstream changed the shape - update patch.mjs anchors and bump PATCH_REVISION.`);
		}
		edit.__find = matched[0];
	}
	if (!existsSync(backup)) {
		copyFileSync(target, backup);
		log(`backup written: ${backup}`);
	}
	let patched = content;
	for (const edit of edits) patched = patched.replace(edit.__find, edit.replace);
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
