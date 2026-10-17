#!/usr/bin/env node
// chezmoi-pi-patch:settlement-abort v2
// Preserve cancellation across low-level runs through the settlement boundary.
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, readdirSync, renameSync, unlinkSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { piCodingAgentRoot } from "../pi-root.mjs";

const NAME = "settlement-abort";
const REVISION = 2;
const MARKER = `chezmoi-pi-patch:${NAME}`;
const VERSION_MARKER = `${MARKER} v${REVISION}`;
const STATE_DIR = join(homedir(), ".local", "state", "chezmoi-pi-patches");
const STATE_FILE = join(STATE_DIR, `${NAME}.json`);
const checkOnly = process.argv.includes("--check");
const profile = process.env.PI_CHEZMOI_PROFILE ?? "";
const wantPatched = profile === "personal" || profile === "axon-work-computer";
const isolated = Boolean(process.env.PI_SETTLEMENT_ABORT_PACKAGE);
const log = (message) => console.log(`[pi-patch:${NAME}] ${message}`);

function fail(message) {
	throw new Error(message);
}

function packageRoot() {
	return process.env.PI_SETTLEMENT_ABORT_PACKAGE || piCodingAgentRoot();
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
	const needle = "async _runAgentPrompt(messages){";
	const matches = readdirSync(directory)
		.filter((name) => name.endsWith(".js"))
		.filter((name) => readFileSync(join(directory, name), "utf8").includes(needle));
	if (matches.length !== 1) {
		fail(`Expected one Pi bundle containing the agent operation anchor, found ${matches.length}; update this patch for the installed Pi version`);
	}
	return join("dist", "bundle", "chunks", matches[0]);
}

const edits = {
	"dist/core/agent-session.js": [
		{
			name: "v2 internal idle wait",
			before: `        if (this.isIdle) {
            return;
        }
        await this._getIdleWaitPromise();`,
			after: `        if (!this.isStreaming && !this.isCompacting) {
            return;
        }
        await this._getIdleWaitPromise();`,
		},
		{
			name: "v2 internal idle resolver",
			before: `if (!this.isIdle || !this._resolveIdleWait)`,
			after: `if (this.isStreaming || this.isCompacting || !this._resolveIdleWait)`,
		},
		{
			name: "settlement busy state",
			before: `    /** Whether the session is currently processing an agent run or post-run continuation. */
    get isStreaming() {
        return this._isAgentRunActive;
    }`,
			after: `    /** Whether the session is processing an agent run, continuation, or awaited final settlement. */
    get isStreaming() {
        return this._isAgentRunActive || this._isEmittingAgentSettled;
    }`,
		},

		{
			name: "custom triggered delivery",
            before: `else if (this.isStreaming && options?.triggerTurn !== false) {`,
            after: `else if (this.isStreaming && !this._isEmittingAgentSettled && options?.triggerTurn !== false) {`,
        },
        {
            name: "custom immediate delivery",
            before: `else if (this.isStreaming) {
            // Appending now`,
            after: `else if (this.isStreaming && !this._isEmittingAgentSettled) {
            // Appending now`,
        },
        {
            name: "operation controller",
			before: `    async _runAgentPrompt(messages) {`,
			after: `    async _runAgentPrompt(messages) {
        // ${VERSION_MARKER}
        const operationAbortController = new AbortController();
        this._operationAbortController = operationAbortController;`,
		},
		{
			name: "operation cleanup",
			before: `        finally {
            if (this._agentRunAbortRequested)
                this._finishCancelledRetry();
            this._failedResponse = undefined;
            this._runSystemPromptOptions = undefined;
            this._flushPendingBashMessages();
            this._flushPendingCustomMessages();
            await this._emitAgentSettled();
        }`,
			after: `        finally {
            try {
                if (this._agentRunAbortRequested)
                    this._finishCancelledRetry();
                this._failedResponse = undefined;
                this._runSystemPromptOptions = undefined;
                this._flushPendingBashMessages();
                this._flushPendingCustomMessages();
                await this._emitAgentSettled();
            }
            finally {
                if (this._operationAbortController === operationAbortController)
                    this._operationAbortController = undefined;
            }
        }`,
		},
		{
			name: "settled controller capture",
			before: `    async _emitAgentSettled() {`,
			after: `    async _emitAgentSettled() {
        const operationAbortController = this._operationAbortController;`,
		},
		{
			name: "settled cleanup before deferred prompts",
			before: `            this._isEmittingAgentSettled = false;
        }
        const deferred = this._deferredSettledActions.splice(0);`,
			after: `            this._isEmittingAgentSettled = false;
            if (this._operationAbortController === operationAbortController)
                this._operationAbortController = undefined;
        }
        const deferred = this._deferredSettledActions.splice(0);`,
		},
		{
			name: "abort signal",
			before: `    async abort() {`,
			after: `    async abort() {
        this._operationAbortController?.abort();`,
		},
		{
			name: "signal context",
			before: `getSignal: () => this.agent.signal,`,
			after: `getSignal: () => this._operationAbortController?.signal ?? this.agent.signal,`,
		},
		{
			name: "discard proposals",
			before: `            this._commitBoundaryDrafts(result.entries);
            this._flushPendingCustomMessages();
            const finalContext = this._buildBoundaryContext([], "agent_before_settle");`,
			after: `            if (this._agentRunAbortRequested || this._abortDuringBeforeSettle)
                return false;
            this._commitBoundaryDrafts(result.entries);
            this._flushPendingCustomMessages();
            const finalContext = this._buildBoundaryContext([], "agent_before_settle");`,
		}
	],
	"dist/core/extensions/types.d.ts": [
		{
			name: "signal contract",
			before: `    /** The current abort signal, or undefined when the agent is not streaming. */`,
			after: `    /** Current operation cancellation signal, including awaited agent_before_settle and agent_settled handlers; undefined outside an operation (main-agent idle may be true during final settlement). */
    // ${VERSION_MARKER}`,
		}
	]
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
			name: "v2 internal idle wait",
			before: `async waitForIdle(){this.isIdle||await this._getIdleWaitPromise()}`,
			after: `async waitForIdle(){!this.isStreaming&&!this.isCompacting||await this._getIdleWaitPromise()}`,
		},
		{
			name: "v2 internal idle resolver",
			before: `if(!this.isIdle||!this._resolveIdleWait)return;`,
			after: `if(this.isStreaming||this.isCompacting||!this._resolveIdleWait)return;`,
		},
		{
			name: "settlement busy state",
			before: `get isStreaming(){return this._isAgentRunActive}`,
			after: `get isStreaming(){return this._isAgentRunActive||this._isEmittingAgentSettled}`,
		},

		{
			name: "custom triggered delivery",
            before: `else if(this.isStreaming&&options?.triggerTurn!==!1)`,
            after: `else if(this.isStreaming&&!this._isEmittingAgentSettled&&options?.triggerTurn!==!1)`,
        },
        {
            name: "custom immediate delivery",
            before: `else this.isStreaming?this._pendingCustomMessages.push(appMessage):this._appendCustomMessage(appMessage)`,
            after: `else this.isStreaming&&!this._isEmittingAgentSettled?this._pendingCustomMessages.push(appMessage):this._appendCustomMessage(appMessage)`,
        },
        {
            name: "operation controller",
			before: `async _runAgentPrompt(messages){`,
			after: `async _runAgentPrompt(messages){/* ${VERSION_MARKER} */const operationAbortController=new AbortController;this._operationAbortController=operationAbortController;`,
		},
		{
			name: "operation cleanup",
			before: `finally{this._agentRunAbortRequested&&this._finishCancelledRetry(),this._failedResponse=void 0,this._runSystemPromptOptions=void 0,this._flushPendingBashMessages(),this._flushPendingCustomMessages(),await this._emitAgentSettled()}`,
			after: `finally{try{this._agentRunAbortRequested&&this._finishCancelledRetry(),this._failedResponse=void 0,this._runSystemPromptOptions=void 0,this._flushPendingBashMessages(),this._flushPendingCustomMessages(),await this._emitAgentSettled()}finally{if(this._operationAbortController===operationAbortController)this._operationAbortController=void 0}}`,
		},
		{
			name: "settled controller capture",
			before: `async _emitAgentSettled(){`,
			after: `async _emitAgentSettled(){const operationAbortController=this._operationAbortController;`,
		},
		{
			name: "settled cleanup before deferred prompts",
			before: `finally{this._isEmittingAgentSettled=!1}let deferred=this._deferredSettledActions.splice(0);`,
			after: `finally{this._isEmittingAgentSettled=!1;if(this._operationAbortController===operationAbortController)this._operationAbortController=void 0}let deferred=this._deferredSettledActions.splice(0);`,
		},
		{
			name: "abort signal",
			before: `async abort(){this._isAgentRunActive`,
			after: `async abort(){this._operationAbortController?.abort();this._isAgentRunActive`,
		},
		{
			name: "signal context",
			before: `getSignal:()=>this.agent.signal`,
			after: `getSignal:()=>this._operationAbortController?.signal??this.agent.signal`,
		},
		{
			name: "discard proposals",
			before: `this._commitBoundaryDrafts(result.entries),this._flushPendingCustomMessages();let finalContext=this._buildBoundaryContext([],"agent_before_settle");`,
			after: `if(this._agentRunAbortRequested||this._abortDuringBeforeSettle)return!1;this._commitBoundaryDrafts(result.entries),this._flushPendingCustomMessages();let finalContext=this._buildBoundaryContext([],"agent_before_settle");`,
		}
	];

	for (const relative of Object.keys(edits)) {
		if (!existsSync(join(root, relative))) fail(`Required Pi file is missing: ${relative}`);
	}

	// Only the complete exact v1 block set is a supported upgrade input.
	// Normalize in memory; validate every file before writing any target.
	const legacyEdits = Object.fromEntries(Object.entries(edits).map(([relative, replacements]) => [relative,
		replacements.filter((edit) => !edit.name.startsWith("v2 ")).map((edit) => ({ ...edit, after: edit.after.replaceAll(VERSION_MARKER, `${MARKER} v1`).replace("undefined outside an operation (main-agent idle may be true during final settlement).", "undefined while idle.") }))]));
	legacyEdits["dist/core/agent-session.js"].push({
		name: "legacy idle", before: "        return !this._isAgentRunActive && !this.isCompacting;",
		after: "        return !this.isStreaming && !this.isCompacting;",
	});
	legacyEdits[bundleFile].push({
		name: "legacy idle", before: "get isIdle(){return!this._isAgentRunActive&&!this.isCompacting}",
		after: "get isIdle(){return!this.isStreaming&&!this.isCompacting}",
	});
	const originals = new Map(Object.keys(edits).map((relative) => [relative, readFileSync(join(root, relative), "utf8")]));
	const legacy = [...originals.values()].some((text) => text.includes(`${MARKER} v1`));
	const normalized = new Map(originals);
	if (legacy) {
		for (const [relative, replacements] of Object.entries(legacyEdits)) {
			let text = originals.get(relative);
			if (count(text, MARKER) !== count(replacements.map((edit) => edit.after).join(""), MARKER)
				|| text.includes(VERSION_MARKER)) fail(`Unknown or mixed legacy markers in ${relative}; no files were changed`);
			for (const edit of replacements) {
				if (count(text, edit.after) !== 1) fail(`Incomplete legacy v1 block ${edit.name} in ${relative}; no files were changed`);
			}
			for (const edit of [...replacements].reverse()) text = text.replace(edit.after, edit.before);
			normalized.set(relative, text);
		}
		if (checkOnly) fail("Legacy v1 requires an explicit apply/upgrade; no files were changed");
	}
	// v2 deliberately preserves upstream main-agent idle semantics, independent
	// of the streaming flag used by Escape and RPC during awaited settlement.
	for (const relative of ["dist/core/agent-session.js", bundleFile]) {
		const idle = legacyEdits[relative].at(-1);
		if (count(normalized.get(relative), idle.before) !== 1 || count(normalized.get(relative), idle.after) !== 0)
			fail(`Unknown idle getter in ${relative}; no files were changed`);
	}

	const prepared = [];
	const states = [];
	for (const [relative, replacements] of Object.entries(edits)) {
		const target = join(root, relative);
		const original = normalized.get(relative);
		if (!legacy && original.includes(MARKER) && (!original.includes(VERSION_MARKER) || count(original, MARKER) !== count(replacements.map((edit) => edit.after).join(""), MARKER)))
			fail(`Unknown patch revision or markers in ${relative}; no files were changed`);
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
		prepared.push({ target, relative, original: originals.get(relative), content });
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
