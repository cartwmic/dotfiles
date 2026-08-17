import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { test } from "node:test";
import {
	readConfiguredEditor,
	resolveEditorCommand,
	runInspectPrompt,
	shouldOpenEditor,
	type InspectPromptContext,
} from "./helpers.ts";

test("resolveEditorCommand: configured externalEditor wins over VISUAL/EDITOR", () => {
	assert.equal(
		resolveEditorCommand({
			configuredEditor: "code -w",
			env: { VISUAL: "vim", EDITOR: "nano" },
			platform: "darwin",
		}),
		"code -w",
	);
});

test("resolveEditorCommand: blank configured editor is unset", () => {
	assert.equal(
		resolveEditorCommand({
			configuredEditor: "   ",
			env: { VISUAL: "vim", EDITOR: "emacs" },
			platform: "darwin",
		}),
		"vim",
	);
});

test("resolveEditorCommand: VISUAL then EDITOR then platform default", () => {
	assert.equal(
		resolveEditorCommand({ env: { VISUAL: "vim", EDITOR: "emacs" }, platform: "darwin" }),
		"vim",
	);
	assert.equal(resolveEditorCommand({ env: { EDITOR: "emacs" }, platform: "linux" }), "emacs");
	assert.equal(resolveEditorCommand({ env: {}, platform: "linux" }), "nano");
	assert.equal(resolveEditorCommand({ env: {}, platform: "win32" }), "notepad");
});

test("readConfiguredEditor: project externalEditor wins over global", () => {
	const root = fs.mkdtempSync(path.join(os.tmpdir(), "inspect-prompt-settings-"));
	const cwd = path.join(root, "proj");
	const agentDir = path.join(root, "agent");
	fs.mkdirSync(path.join(cwd, ".pi"), { recursive: true });
	fs.mkdirSync(agentDir, { recursive: true });
	fs.writeFileSync(path.join(agentDir, "settings.json"), JSON.stringify({ externalEditor: "vim" }));
	fs.writeFileSync(
		path.join(cwd, ".pi", "settings.json"),
		JSON.stringify({ externalEditor: "code -w" }),
	);
	assert.equal(readConfiguredEditor({ cwd, agentDir }), "code -w");
	fs.rmSync(root, { recursive: true, force: true });
});

test("readConfiguredEditor: falls back to global when project omits the key", () => {
	const root = fs.mkdtempSync(path.join(os.tmpdir(), "inspect-prompt-settings-"));
	const cwd = path.join(root, "proj");
	const agentDir = path.join(root, "agent");
	fs.mkdirSync(path.join(cwd, ".pi"), { recursive: true });
	fs.mkdirSync(agentDir, { recursive: true });
	fs.writeFileSync(path.join(agentDir, "settings.json"), JSON.stringify({ externalEditor: "hx" }));
	fs.writeFileSync(path.join(cwd, ".pi", "settings.json"), JSON.stringify({ theme: "dark" }));
	assert.equal(readConfiguredEditor({ cwd, agentDir }), "hx");
	fs.rmSync(root, { recursive: true, force: true });
});

test("shouldOpenEditor: true only when hasUI and idle", () => {
	assert.equal(shouldOpenEditor({ hasUI: true, idle: true }), true);
	assert.equal(shouldOpenEditor({ hasUI: false, idle: true }), false);
	assert.equal(shouldOpenEditor({ hasUI: true, idle: false }), false);
	assert.equal(shouldOpenEditor({ hasUI: false, idle: false }), false);
});

function mockCtx(overrides: Partial<InspectPromptContext> & { idle?: boolean } = {}): {
	ctx: InspectPromptContext;
	notifies: Array<{ message: string; type?: string }>;
	forbidden: string[];
} {
	const notifies: Array<{ message: string; type?: string }> = [];
	const forbidden: string[] = [];
	const idle = overrides.idle ?? true;
	const ctx = {
		hasUI: true,
		mode: "tui",
		cwd: "/tmp",
		isIdle: () => idle,
		getSystemPrompt: () => "assembled prompt body",
		ui: {
			notify: (message: string, type?: "info" | "warning" | "error") => {
				notifies.push({ message, type });
			},
		},
		sendUserMessage: () => {
			forbidden.push("sendUserMessage");
		},
		compact: () => {
			forbidden.push("compact");
		},
		reload: () => {
			forbidden.push("reload");
		},
		abort: () => {
			forbidden.push("abort");
		},
		...overrides,
	} as InspectPromptContext;
	return { ctx, notifies, forbidden };
}

test("runInspectPrompt: hasUI false does not spawn or wait on an editor", async () => {
	let spawned = 0;
	const { ctx, notifies } = mockCtx({ hasUI: false, mode: "print" });
	await runInspectPrompt(ctx, {
		spawnEditor: async () => {
			spawned += 1;
			return 0;
		},
		pauseTui: async (fn) => {
			spawned += 10;
			await fn();
		},
	});
	assert.equal(spawned, 0);
	assert.equal(notifies.length, 0);
});

test("runInspectPrompt: not idle notifies and does not spawn", async () => {
	let spawned = 0;
	const { ctx, notifies } = mockCtx({ idle: false });
	await runInspectPrompt(ctx, {
		spawnEditor: async () => {
			spawned += 1;
			return 0;
		},
	});
	assert.equal(spawned, 0);
	assert.equal(notifies.length, 1);
	assert.match(notifies[0].message, /idle/);
});

test("runInspectPrompt: snapshot body, TUI pause/resume, discard writes, delete temp, no turn APIs", async () => {
	const order: string[] = [];
	let spawnedFile = "";
	let spawnedCommand = "";
	let snapshotOnDisk = "";
	const { ctx, notifies, forbidden } = mockCtx();
	(ctx.ui as InspectPromptContext["ui"]).custom = async (factory) => {
		const tui = {
			stop: () => order.push("stop"),
			start: () => order.push("start"),
		};
		await factory(tui, {}, {}, () => order.push("done"));
		return undefined;
	};

	await runInspectPrompt(ctx, {
		resolveEditorCommand: () => "vim",
		spawnEditor: async (command, filePath) => {
			spawnedCommand = command;
			spawnedFile = filePath;
			snapshotOnDisk = fs.readFileSync(filePath, "utf-8");
			fs.writeFileSync(filePath, "operator edited this");
			order.push("spawn");
			return 0;
		},
	});

	assert.equal(spawnedCommand, "vim");
	assert.equal(snapshotOnDisk, "assembled prompt body");
	assert.deepEqual(order, ["stop", "spawn", "start", "done"]);
	assert.equal(fs.existsSync(spawnedFile), false);
	assert.equal(fs.existsSync(path.dirname(spawnedFile)), false);
	assert.equal(forbidden.length, 0);
	assert.match(notifies.at(-1)?.message ?? "", /not applied/);
});
