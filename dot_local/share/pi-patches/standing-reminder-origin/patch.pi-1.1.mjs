#!/usr/bin/env node
// chezmoi-pi-patch:standing-reminder-origin v2
// Carry input source on the exact user-message object until message_start.
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, readdirSync, renameSync, unlinkSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { piCodingAgentRoot } from "../pi-root.mjs";

const NAME = "standing-reminder-origin";
const REVISION = 2;
const MARKER = `chezmoi-pi-patch:${NAME}`;
const VERSION_MARKER = `${MARKER} v${REVISION}`;
const STATE_DIR = join(homedir(), ".local", "state", "chezmoi-pi-patches");
const STATE_FILE = join(STATE_DIR, `${NAME}.json`);
const checkOnly = process.argv.includes("--check");
const profile = process.env.PI_CHEZMOI_PROFILE ?? "";
const wantPatched = profile === "personal" || profile === "axon-work-computer";
const isolated = Boolean(process.env.PI_STANDING_REMINDER_ORIGIN_PACKAGE);
const log = (message) => console.log(`[pi-patch:${NAME}] ${message}`);

function fail(message) {
	throw new Error(message);
}

function packageRoot() {
	return process.env.PI_STANDING_REMINDER_ORIGIN_PACKAGE || piCodingAgentRoot();
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
			patchName: NAME,
			patchRevision: REVISION,
			marker: MARKER,
			status,
			target,
			profile: profile || "(unset)",
			version,
			targets,
			when: new Date().toISOString(),
		}, null, 2));
	} catch (error) {
		log(`WARN: could not write state receipt: ${error.message}`);
	}
}

function locateBundle(root) {
	const directory = join(root, "dist", "bundle", "chunks");
	if (!existsSync(directory)) fail(`Pi bundle directory not found: ${directory}`);
	const needle = "async _queueUserInput(text,images,behavior,source){";
	const matches = readdirSync(directory)
		.filter((name) => name.endsWith(".js"))
		.filter((name) => readFileSync(join(directory, name), "utf8").includes(needle));
	if (matches.length !== 1) {
		fail(`Expected one Pi bundle containing the input queue anchor, found ${matches.length}; update this patch for the installed Pi version`);
	}
	return join("dist", "bundle", "chunks", matches[0]);
}

const edits = {
	"dist/core/agent-session.js": [
		{
			name: "per-message origin map",
			before: "    _entryIdsByMessage = new WeakMap();",
			after: `    _entryIdsByMessage = new WeakMap();\n    // ${VERSION_MARKER}\n    _inputSources = new WeakMap();`,
		},
		{
			name: "initial prompt origin",
			before: `        messages.push({
            role: "user",
            content: userContent,
            timestamp: Date.now(),
        });`,
			after: `        const userMessage = {
            role: "user",
            content: userContent,
            timestamp: Date.now(),
        };
        this._inputSources.set(userMessage, options?.source ?? "interactive");
        messages.push(userMessage);`,
		},
		{
			name: "streaming prompt origin",
			before: `            if (options.streamingBehavior === "followUp") {
                await this._queueFollowUp(expandedText, currentImages);
            }
            else {
                await this._queueSteer(expandedText, currentImages);
            }`,
			after: `            if (options.streamingBehavior === "followUp") {
                await this._queueFollowUp(expandedText, currentImages, options?.source ?? "interactive");
            }
            else {
                await this._queueSteer(expandedText, currentImages, options?.source ?? "interactive");
            }`,
		},
		{
			name: "queued prompt origin",
			before: `        if (behavior === "steer") {
            await this._queueSteer(expandedText, processedInput.images);
        }
        else {
            await this._queueFollowUp(expandedText, processedInput.images);
        }`,
			after: `        if (behavior === "steer") {
            await this._queueSteer(expandedText, processedInput.images, source);
        }
        else {
            await this._queueFollowUp(expandedText, processedInput.images, source);
        }`,
		},
		{
			name: "steering message identity",
			before: `    async _queueSteer(text, images) {
        this._steeringMessages.push(text);
        this._emitQueueUpdate();
        const content = [{ type: "text", text }];
        if (images) {
            content.push(...images);
        }
        this.agent.steer({
            role: "user",
            content,
            timestamp: Date.now(),
        });
    }`,
			after: `    async _queueSteer(text, images, source = "interactive") {
        this._steeringMessages.push(text);
        this._emitQueueUpdate();
        const content = [{ type: "text", text }];
        if (images) {
            content.push(...images);
        }
        const message = { role: "user", content, timestamp: Date.now() };
        this._inputSources.set(message, source);
        this.agent.steer(message);
    }`,
		},
		{
			name: "follow-up message identity",
			before: `    async _queueFollowUp(text, images) {
        this._followUpMessages.push(text);
        this._emitQueueUpdate();
        const content = [{ type: "text", text }];
        if (images) {
            content.push(...images);
        }
        this.agent.followUp({ role: "user", content, timestamp: Date.now() });
    }`,
			after: `    async _queueFollowUp(text, images, source = "interactive") {
        this._followUpMessages.push(text);
        this._emitQueueUpdate();
        const content = [{ type: "text", text }];
        if (images) {
            content.push(...images);
        }
        const message = { role: "user", content, timestamp: Date.now() };
        this._inputSources.set(message, source);
        this.agent.followUp(message);
    }`,
		},
		{
			name: "processed message origin event",
			before: `            const extensionEvent = {
                type: "message_start",
                message: event.message,
            };`,
			after: `            const extensionEvent = {
                type: "message_start",
                message: event.message,
                source: event.message.role === "user" ? this._inputSources.get(event.message) : undefined,
            };`,
		},
	],
	"dist/core/extensions/types.d.ts": [
		{
			name: "message_start origin type",
			before: `export interface MessageStartEvent {
    type: "message_start";
    message: AgentMessage;
}`,
			after: `export interface MessageStartEvent {
    type: "message_start";
    message: AgentMessage;
    /** Captured origin of this exact user message; absent when the message was not created from a known input. */
    // ${VERSION_MARKER}
    source?: InputSource;
}`,
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
			name: "per-message origin map",
			before: "_entryIdsByMessage=new WeakMap;",
			after: `_entryIdsByMessage=new WeakMap;/* ${VERSION_MARKER} */_inputSources=new WeakMap;`,
		},
		{
			name: "initial prompt origin",
			before: `userContent=[{type:"text",text:userText}];userContent.push(...normalized.images),messages.push({role:"user",content:userContent,timestamp:Date.now()});`,
			after: `userContent=[{type:"text",text:userText}];userContent.push(...normalized.images);let userMessage={role:"user",content:userContent,timestamp:Date.now()};this._inputSources.set(userMessage,options?.source??"interactive"),messages.push(userMessage);`,
		},
		{
			name: "streaming prompt origin",
			before: `options.streamingBehavior==="followUp"?await this._queueFollowUp(expandedText,currentImages):await this._queueSteer(expandedText,currentImages)`,
			after: `options.streamingBehavior==="followUp"?await this._queueFollowUp(expandedText,currentImages,options?.source??"interactive"):await this._queueSteer(expandedText,currentImages,options?.source??"interactive")`,
		},
		{
			name: "queued prompt origin",
			before: `behavior==="steer"?await this._queueSteer(expandedText,processedInput.images):await this._queueFollowUp(expandedText,processedInput.images)`,
			after: `behavior==="steer"?await this._queueSteer(expandedText,processedInput.images,source):await this._queueFollowUp(expandedText,processedInput.images,source)`,
		},
		{
			name: "steering message identity",
			before: `async _queueSteer(text,images){this._steeringMessages.push(text),this._emitQueueUpdate();let content=[{type:"text",text}];images&&content.push(...images),this.agent.steer({role:"user",content,timestamp:Date.now()})}`,
			after: `async _queueSteer(text,images,source="interactive"){this._steeringMessages.push(text),this._emitQueueUpdate();let content=[{type:"text",text}];images&&content.push(...images);let message={role:"user",content,timestamp:Date.now()};this._inputSources.set(message,source),this.agent.steer(message)}`,
		},
		{
			name: "follow-up message identity",
			before: `async _queueFollowUp(text,images){this._followUpMessages.push(text),this._emitQueueUpdate();let content=[{type:"text",text}];images&&content.push(...images),this.agent.followUp({role:"user",content,timestamp:Date.now()})}`,
			after: `async _queueFollowUp(text,images,source="interactive"){this._followUpMessages.push(text),this._emitQueueUpdate();let content=[{type:"text",text}];images&&content.push(...images);let message={role:"user",content,timestamp:Date.now()};this._inputSources.set(message,source),this.agent.followUp(message)}`,
		},
		{
			name: "processed message origin event",
			before: `let extensionEvent={type:"message_start",message:event.message};`,
			after: `let extensionEvent={type:"message_start",message:event.message,/* ${VERSION_MARKER} */source:event.message.role==="user"?this._inputSources.get(event.message):void 0};`,
		},
	];

	for (const relative of Object.keys(edits)) {
		if (!existsSync(join(root, relative))) fail(`Required Pi file is missing: ${relative}`);
	}

	const prepared = [];
	const states = [];
	for (const [relative, replacements] of Object.entries(edits)) {
		const target = join(root, relative);
		const original = readFileSync(target, "utf8");
		for (const edit of replacements) {
			const beforeCount = count(original, edit.before);
			const afterCount = count(original, edit.after);
			if (afterCount === 1) continue;
			if (afterCount !== 0 || beforeCount !== 1) {
				fail(`Changed or ambiguous anchor for ${edit.name} in ${relative} (before=${beforeCount}, after=${afterCount}); update this patch rather than guessing`);
			}
		}
		const patchedCount = replacements.filter((edit) => count(original, edit.after) === 1).length;
		const state = patchedCount === 0 ? "unpatched"
			: patchedCount === replacements.length ? "patched" : "partial";
		states.push(state);
		let content = original;
		if (state === "unpatched" && wantPatched) {
			for (const edit of replacements) content = content.replace(edit.before, edit.after);
		} else if (state === "patched" && !wantPatched) {
			for (const edit of [...replacements].reverse()) content = content.replace(edit.after, edit.before);
		}
		prepared.push({ target, relative, original, content });
	}

	if (states.includes("partial") || new Set(states).size > 1) {
		fail(`Patch is partially applied across Pi files (${states.join(", ")}); no files were changed`);
	}
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
		for (const file of changing.filter((file) => file.target.endsWith(".js"))) {
			file.tmp = `${file.target}.${NAME}.tmp.js`;
			temporary.push(file.tmp);
			writeFileSync(file.tmp, file.content);
			execFileSync(process.execPath, ["--check", file.tmp], { stdio: "pipe" });
		}
		for (const file of changing.filter((file) => !file.tmp)) {
			file.tmp = `${file.target}.${NAME}.tmp`;
			temporary.push(file.tmp);
			writeFileSync(file.tmp, file.content);
		}
		// All anchors and rewritten JavaScript have been validated before any target changes.
		for (const file of changing) {
			renameSync(file.tmp, file.target);
			log(`${wantPatched ? "patched" : "unpatched"} ${file.target}`);
		}
	} finally {
		for (const temp of temporary) if (existsSync(temp)) unlinkSync(temp);
	}

	const status = wantPatched ? "patched" : "unpatched";
	const sessionTarget = join(root, "dist/core/agent-session.js");
	writeState(status, sessionTarget, version, prepared.map((file) => ({
		target: file.target,
		sha256: sha256(file.content),
	})));
	log(currentState === expectedState ? `already ${status}` : `${status} for profile=${profile || "(unset)"}`);
} catch (error) {
	console.error(`[pi-patch:${NAME}] ERROR: ${error.message}`);
	process.exit(1);
}
