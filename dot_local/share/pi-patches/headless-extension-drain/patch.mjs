#!/usr/bin/env node
// Durable chezmoi patch for Pi's fire-and-forget extension work in print mode.
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { copyFileSync, existsSync, mkdirSync, readFileSync, readdirSync, renameSync, unlinkSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const name = "headless-extension-drain";
const marker = `chezmoi-pi-patch:${name} v1`;
const log = (text) => console.log(`[pi-patch:${name}] ${text}`);
const check = process.argv.includes("--check");
// Test a copied package without modifying the installed CLI.
const root = process.env.PI_HEADLESS_PATCH_PACKAGE ?? join(
	execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim(),
	"@earendil-works/pi-coding-agent",
);
const edits = {
	"dist/core/agent-session.js": [
		[
			"    async _runAgentPrompt(messages) {",
			`    // ${marker}
    // Extension compact/sendUserMessage are intentionally fire-and-forget.
    // The print host must own them through callbacks and resumed prompts, but
    // abort()/waitForIdle() must NOT wait on them (compact itself awaits abort).
    _extensionTasks = new Set();
    _extensionTaskError = undefined;
    _trackExtensionTask(task) {
        this._extensionTasks.add(task);
        task.then(() => this._extensionTasks.delete(task), (error) => {
            this._extensionTasks.delete(task);
            this._extensionTaskError = error;
        });
    }
    async waitForExtensionTasks() {
        while (this._extensionTasks.size > 0) {
            await Promise.allSettled([...this._extensionTasks]);
        }
        const error = this._extensionTaskError;
        this._extensionTaskError = undefined;
        if (error !== undefined) throw error;
    }
    async _runAgentPrompt(messages) {`,
		],
		[
			`                this.sendUserMessage(content, options).catch((err) => {
                    runner.emitError({
                        extensionPath: "<runtime>",
                        event: "send_user_message",
                        error: err instanceof Error ? err.message : String(err),
                    });
                });`,
			`                // ${marker}
                this._trackExtensionTask(this.sendUserMessage(content, options).catch((err) => {
                    runner.emitError({
                        extensionPath: "<runtime>",
                        event: "send_user_message",
                        error: err instanceof Error ? err.message : String(err),
                    });
                    throw err;
                }));`,
		],
		[
			`            compact: (options) => {
                void (async () => {
                    try {
                        const result = await this.compact(options?.customInstructions);
                        options?.onComplete?.(result);
                    }
                    catch (error) {
                        const err = error instanceof Error ? error : new Error(String(error));
                        options?.onError?.(err);
                    }
                })();
            },`,
			`            compact: (options) => {
                // ${marker}
                this._trackExtensionTask((async () => {
                    try {
                        const result = await this.compact(options?.customInstructions);
                        options?.onComplete?.(result);
                    }
                    catch (error) {
                        const err = error instanceof Error ? error : new Error(String(error));
                        if (!options?.onError) throw err;
                        options.onError(err);
                    }
                })());
            },`,
		],
	],
	"dist/modes/print-mode.js": [
		[
			`            await session.prompt(initialMessage, { images: initialImages });`,
			`            await session.prompt(initialMessage, { images: initialImages });
            // ${marker}
            await session.waitForExtensionTasks();`,
		],
		[
			`            await session.prompt(message);`,
			`            await session.prompt(message);
            // ${marker}
            await session.waitForExtensionTasks();`,
		],
	],
};

try {
	if (!existsSync(join(root, "package.json"))) {
		if (check) throw new Error("Pi is not installed; cannot verify");
		log("Pi is not installed; skipped");
		process.exit(0);
	}
	// The npm executable loads the bundle, not dist/core. Patch both surfaces.
	const chunks = join(root, "dist/bundle/chunks");
	const matches = readdirSync(chunks).filter((file) => file.endsWith(".js") &&
		readFileSync(join(chunks, file), "utf8").includes("async function runPrintMode(runtimeHost,options)"));
	if (matches.length !== 1) throw new Error(`Expected one print-mode bundle, found ${matches.length}`);
	const sessionEdits = edits["dist/core/agent-session.js"];
	const bundleFile = `dist/bundle/chunks/${matches[0]}`;
	const bundleSource = readFileSync(join(root, bundleFile), "utf8");
	// Upstream renamed the print prompt-loop variable between 0.85.0 (message2)
	// and 0.85.1 (message). Detect the variant, including an already-patched
	// bundle, so re-runs skip instead of failing on the renamed anchor.
	const loopVar = bundleSource.includes("for(let message of messages)await session.prompt(message);") ? "message"
		: bundleSource.includes("for(let message2 of messages)await session.prompt(message2);") ? "message2"
		: bundleSource.includes("for(let message2 of messages){await session.prompt(message2);await session.waitForExtensionTasks();}") ? "message2"
		: bundleSource.includes("for(let message of messages){await session.prompt(message);await session.waitForExtensionTasks();}") ? "message"
		: undefined;
	if (!loopVar) throw new Error(`Changed upstream anchor in ${bundleFile}; update this patch, do not guess`);
	edits[bundleFile] = [
		["async _runAgentPrompt(messages){", sessionEdits[0][1].replace("    async _runAgentPrompt(messages) {", "async _runAgentPrompt(messages){")],
		['sendUserMessage:(content,options)=>{this.sendUserMessage(content,options).catch(err2=>{runner.emitError({extensionPath:"<runtime>",event:"send_user_message",error:err2 instanceof Error?err2.message:String(err2)})})}',
		 `sendUserMessage:(content,options)=>{/* ${marker} */this._trackExtensionTask(this.sendUserMessage(content,options).catch(err2=>{runner.emitError({extensionPath:"<runtime>",event:"send_user_message",error:err2 instanceof Error?err2.message:String(err2)});throw err2;}))}`],
		['compact:options=>{(async()=>{try{let result=await this.compact(options?.customInstructions);options?.onComplete?.(result)}catch(error){let err2=error instanceof Error?error:new Error(String(error));options?.onError?.(err2)}})()}',
		 `compact:options=>{/* ${marker} */this._trackExtensionTask((async()=>{try{let result=await this.compact(options?.customInstructions);options?.onComplete?.(result)}catch(error){let err2=error instanceof Error?error:new Error(String(error));if(!options?.onError)throw err2;options.onError(err2)}})())}`],
		[`initialMessage&&await session.prompt(initialMessage,{images:initialImages});for(let ${loopVar} of messages)await session.prompt(${loopVar});`,
		 `initialMessage&&(await session.prompt(initialMessage,{images:initialImages}),await session.waitForExtensionTasks());/* ${marker} */for(let ${loopVar} of messages){await session.prompt(${loopVar});await session.waitForExtensionTasks();}`],
	];
	const prepared = [];
	for (const [relative, replacements] of Object.entries(edits)) {
		const target = join(root, relative);
		const original = readFileSync(target, "utf8");
		let content = original;
		for (const [before, after] of replacements) {
			if (content.split(after).length === 2) continue;
			if (content.split(before).length !== 2) {
				throw new Error(`Changed upstream anchor in ${relative}; update this patch, do not guess`);
			}
			content = content.replace(before, after);
		}
		if (check && content !== original) throw new Error(`${relative} is not patched`);
		prepared.push({ target, original, content });
	}
	if (check) {
		log("verified all patch blocks");
		process.exit(0);
	}
	// Validate every target before replacing either one.
	const temporary = [];
	try {
		for (const file of prepared.filter((file) => file.original !== file.content)) {
			file.tmp = `${file.target}.chezmoi-pi-patch.tmp.js`;
			temporary.push(file.tmp);
			writeFileSync(file.tmp, file.content);
			execFileSync(process.execPath, ["--check", file.tmp], { stdio: "pipe" });
		}
		for (const file of prepared.filter((file) => file.tmp)) {
			const backup = `${file.target}.orig.chezmoi-pi-patch`;
			if (!existsSync(backup)) copyFileSync(file.target, backup);
			renameSync(file.tmp, file.target);
			log(`patched ${file.target}`);
		}
	} finally {
		for (const tmp of temporary) if (existsSync(tmp)) unlinkSync(tmp);
	}
	const stateDir = join(homedir(), ".local/state/chezmoi-pi-patches");
	// Isolated package probes must not overwrite installed-package receipts.
	if (!process.env.PI_HEADLESS_PATCH_PACKAGE) {
		mkdirSync(stateDir, { recursive: true });
		writeFileSync(join(stateDir, `${name}.json`), JSON.stringify({
			patchName: name, patchRevision: 1, status: "patched", marker,
			target: join(chunks, matches[0]), when: new Date().toISOString(),
			version: JSON.parse(readFileSync(join(root, "package.json"))).version,
			targets: prepared.map(({ target, content }) => ({ target, sha256: createHash("sha256").update(content).digest("hex") })),
		}, null, 2));
	}
	log("applied (already-matching targets unchanged)");
} catch (error) {
	console.error(`[pi-patch:${name}] ERROR: ${error.message}`);
	process.exit(1);
}
