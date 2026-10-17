#!/usr/bin/env node
// chezmoi-pi-patch:prompt-start-race v1
// Queue a prompt that loses the start race instead of throwing or starting a second run.
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, readdirSync, renameSync, unlinkSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { piCodingAgentRoot } from "../pi-root.mjs";

const NAME = "prompt-start-race";
const REVISION = 1;
const MARKER = `chezmoi-pi-patch:${NAME}`;
const VERSION_MARKER = `${MARKER} v${REVISION}`;
const STATE_DIR = join(homedir(), ".local", "state", "chezmoi-pi-patches");
const STATE_FILE = join(STATE_DIR, `${NAME}.json`);
const checkOnly = process.argv.includes("--check");
const profile = process.env.PI_CHEZMOI_PROFILE ?? "";
const wantPatched = profile === "personal" || profile === "axon-work-computer";
const isolated = Boolean(process.env.PI_PROMPT_START_RACE_PACKAGE);
const log = (message) => console.log(`[pi-patch:${NAME}] ${message}`);

function fail(message) {
	throw new Error(message);
}

function packageRoot() {
	return process.env.PI_PROMPT_START_RACE_PACKAGE || piCodingAgentRoot();
}

function count(text, needle) {
	let total = 0;
	let index = 0;
	while ((index = text.indexOf(needle, index)) !== -1) {
		total += 1;
		index += needle.length;
	}
	return total;
}

function sha256(text) {
	return createHash("sha256").update(text).digest("hex");
}

function writeState(status, target, version, targets = []) {
	if (isolated) return;
	try {
		mkdirSync(STATE_DIR, { recursive: true });
		writeFileSync(STATE_FILE, JSON.stringify({
			patchName: NAME, patchRevision: REVISION, marker: MARKER, status, target,
			profile: profile || "(unset)", version, targets, when: new Date().toISOString(),
		}, null, 2));
	} catch (error) {
		log(`WARN: could not write state receipt: ${error.message}`);
	}
}

function locateBundle(root) {
	const directory = join(root, "dist", "bundle", "chunks");
	if (!existsSync(directory)) fail(`Pi bundle directory not found: ${directory}`);
	const needle = "async prompt(text,options){if(this._isEmittingAgentSettled)";
	const matches = readdirSync(directory)
		.filter((name) => name.endsWith(".js"))
		.filter((name) => readFileSync(join(directory, name), "utf8").includes(needle));
	if (matches.length !== 1) {
		fail(`Expected one Pi bundle containing AgentSession.prompt, found ${matches.length}; update this patch for the installed Pi version`);
	}
	return join("dist", "bundle", "chunks", matches[0]);
}

// Two places in prompt() can discover that another prompt already started a run:
// the streaming branch after the awaited input handlers, and the point after the
// last await (image normalization) just before the run starts. Both queue the
// prompt into the active run with its requested delivery, defaulting to steer.
// When settlement-abort is applied, isStreaming also covers awaited final
// settlement after the agent run has ended; nothing would drain a queue then, so
// both points first wait for that settlement and then start or join normally.
const edits = {
	"dist/core/agent-session.js": [
		{
			name: "early wait for final settlement",
			before: `        const { text: currentText, images: currentImages } = processedInput;
`,
			after: `        const { text: currentText, images: currentImages } = processedInput;
        // ${VERSION_MARKER}: only final settlement is running; wait, then start or join normally.
        if (this.isStreaming && !this._isAgentRunActive)
            await this.waitForIdle();
`,
		},
		{
			name: "early streaming branch defaults to steer",
			before: `            if (!options?.streamingBehavior) {
                throw new Error("Agent is already processing. Specify streamingBehavior ('steer' or 'followUp') to queue the message.");
            }`,
			after: `            if (!options?.streamingBehavior) {
                // ${VERSION_MARKER}: a prompt that finds a run already active queues as steer.
                options = { ...options, streamingBehavior: "steer" };
            }`,
		},
		{
			name: "late start check",
			before: `        const normalized = await this._normalizePromptImages(currentImages);
`,
			after: `        const normalized = await this._normalizePromptImages(currentImages);
        // ${VERSION_MARKER}: another prompt started a run during our awaits; join it.
        if (this.isStreaming && !this._isAgentRunActive)
            await this.waitForIdle();
        if (this._isAgentRunActive) {
            if (options?.streamingBehavior === "followUp") {
                await this._queueFollowUp(expandedText, currentImages, options?.source ?? "interactive");
            }
            else {
                await this._queueSteer(expandedText, currentImages, options?.source ?? "interactive");
            }
            preflightResult?.("queued");
            return;
        }
`,
		},
	],
};

try {
	const root = packageRoot();
	if (!root || !existsSync(join(root, "package.json"))) {
		if (checkOnly) fail("@earendil-works/pi-coding-agent is not installed; cannot verify");
		log("pi-coding-agent is not installed; skipped");
		process.exit(0);
	}
	const version = JSON.parse(readFileSync(join(root, "package.json"), "utf8")).version;
	const bundleFile = locateBundle(root);
	edits[bundleFile] = [
		{
			name: "early wait for final settlement",
			before: `let{text:currentText,images:currentImages}=processedInput,expandedText=currentText;`,
			after: `let{text:currentText,images:currentImages}=processedInput,expandedText=currentText;/* ${VERSION_MARKER} settle */this.isStreaming&&!this._isAgentRunActive&&await this.waitForIdle();`,
		},
		{
			name: "early streaming branch defaults to steer",
			before: `if(!options?.streamingBehavior)throw new Error("Agent is already processing. Specify streamingBehavior ('steer' or 'followUp') to queue the message.");`,
			after: `if(!options?.streamingBehavior)options={...options,streamingBehavior:"steer"};/* ${VERSION_MARKER} early */`,
		},
		{
			name: "late start check",
			before: `let normalized=await this._normalizePromptImages(currentImages),userText=`,
			after: `let normalized=await this._normalizePromptImages(currentImages);this.isStreaming&&!this._isAgentRunActive&&await this.waitForIdle();if(this._isAgentRunActive){/* ${VERSION_MARKER} late */options?.streamingBehavior==="followUp"?await this._queueFollowUp(expandedText,currentImages,options?.source??"interactive"):await this._queueSteer(expandedText,currentImages,options?.source??"interactive"),preflightResult?.("queued");return}let userText=`,
		},
	];

	const prepared = [];
	const states = [];
	for (const [relative, replacements] of Object.entries(edits)) {
		const target = join(root, relative);
		if (!existsSync(target)) fail(`Required Pi file is missing: ${relative}`);
		const original = readFileSync(target, "utf8");
		const expectedMarkers = count(replacements.map((edit) => edit.after).join(""), MARKER);
		const markers = count(original, MARKER);
		if (markers !== 0 && (markers !== expectedMarkers || !original.includes(VERSION_MARKER)))
			fail(`Unknown patch revision or markers in ${relative}; no files were changed`);
		for (const edit of replacements) {
			const beforeCount = count(original, edit.before);
			const afterCount = count(original, edit.after);
			if (afterCount === 1) continue;
			if (afterCount !== 0 || beforeCount !== 1)
				fail(`Changed or ambiguous anchor for ${edit.name} in ${relative} (before=${beforeCount}, after=${afterCount}); update this patch rather than guessing`);
		}
		const patchedCount = replacements.filter((edit) => count(original, edit.after) === 1).length;
		const state = patchedCount === 0 ? "unpatched" : patchedCount === replacements.length ? "patched" : "partial";
		states.push(state);
		let content = original;
		if (state === "unpatched" && wantPatched) {
			for (const edit of replacements) content = content.replace(edit.before, edit.after);
		} else if (state === "patched" && !wantPatched) {
			for (const edit of [...replacements].reverse()) content = content.replace(edit.after, edit.before);
		}
		prepared.push({ target, original, content });
	}

	if (states.includes("partial") || new Set(states).size > 1)
		fail(`Patch is partially applied across Pi files (${states.join(", ")}); no files were changed`);
	const currentState = states[0];
	const expectedState = wantPatched ? "patched" : "unpatched";
	if (checkOnly) {
		if (currentState !== expectedState) fail(`profile '${profile || "(unset)"}' expects ${expectedState} files, found ${currentState}`);
		log(`verified all blocks for profile=${profile || "(unset)"}`);
		process.exit(0);
	}

	const changing = prepared.filter((file) => file.content !== file.original);
	const temporary = [];
	try {
		for (const file of changing) {
			file.tmp = `${file.target}.${NAME}.tmp.js`;
			temporary.push(file.tmp);
			writeFileSync(file.tmp, file.content);
			execFileSync(process.execPath, ["--check", file.tmp], { stdio: "pipe" });
		}
		// All anchors and rewritten JavaScript are validated before any target changes.
		for (const file of changing) {
			renameSync(file.tmp, file.target);
			log(`${wantPatched ? "patched" : "unpatched"} ${file.target}`);
		}
	} finally {
		for (const temp of temporary) if (existsSync(temp)) unlinkSync(temp);
	}

	const status = wantPatched ? "patched" : "unpatched";
	writeState(status, join(root, "dist/core/agent-session.js"), version,
		prepared.map((file) => ({ target: file.target, sha256: sha256(file.content) })));
	log(currentState === expectedState ? `already ${status}` : `${status} for profile=${profile || "(unset)"}`);
} catch (error) {
	console.error(`[pi-patch:${NAME}] ERROR: ${error.message}`);
	process.exit(1);
}
