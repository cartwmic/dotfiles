import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { test } from "node:test";
import type { ExtensionAPI, ExtensionContext, SessionEntry } from "@earendil-works/pi-coding-agent";
import extension, { INSPECT_SESSION_COMMAND, INSPECT_SESSION_SHORTCUT } from "./index.ts";
import {
	buildConversationSnapshot,
	captureUiBashComponents,
	clearSessionProgress,
	createSessionProgress,
	finishAssistant,
	finishTool,
	getSessionProgress,
	recordAssistantUpdate,
	recordToolUpdate,
	runInspectSession,
	type BashComponentSnapshot,
} from "./session.ts";

function messageEntry(id: string, role: string, content: unknown, extra: Record<string, unknown> = {}): SessionEntry {
	return {
		type: "message",
		id,
		parentId: null,
		timestamp: "2026-01-01T00:00:00.000Z",
		message: { id: `message-${id}`, role, content, ...extra },
	} as SessionEntry;
}

function bashMessageEntry(id: string, command: string, output: string): SessionEntry {
	return messageEntry(id, "bashExecution", output, {
		command,
		output,
		exitCode: 0,
		cancelled: false,
		truncated: false,
	});
}

class Container {
	children: unknown[];

	constructor(children: unknown[] = []) {
		this.children = children;
	}
}

function fakeTui(
	options: {
		chat?: unknown[];
		pending?: unknown[];
		mode?: string;
		order?: string[];
	} = {},
) {
	const order = options.order ?? [];
	const document = new Container([new Container(), new Container(), new Container(options.chat ?? [])]);
	return {
		mode: options.mode ?? "fullscreen",
		children: [document, new Container(options.pending ?? []), ...Array.from({ length: 5 }, () => new Container())],
		stop: (opts?: { preserveScreen?: boolean }) => order.push(`stop:${String(opts?.preserveScreen)}`),
		start: () => order.push("start"),
	};
}

function fakeBash(
	command: string,
	outputLines: string[],
	area: "chat" | "pending" = "chat",
	status = "complete",
): BashComponentSnapshot & { constructor: { name: string } } {
	return {
		constructor: { name: "BashExecutionComponent" },
		area,
		command,
		status,
		outputLines,
		render: () => [],
	} as BashComponentSnapshot & { constructor: { name: string } };
}

type TestCustomFactory = (
	tui: unknown,
	theme: unknown,
	keybindings: unknown,
	done: (result: unknown) => void,
) => unknown | Promise<unknown>;

function fakeContext(options: {
	cwd?: string;
	branch?: SessionEntry[];
	allEntries?: SessionEntry[];
	idle?: boolean;
	tui?: ReturnType<typeof fakeTui>;
	order?: string[];
} = {}): {
	ctx: ExtensionContext;
	notifications: Array<{ message: string; type?: string }>;
} {
	const notifications: Array<{ message: string; type?: string }> = [];
	const tui = options.tui ?? fakeTui({ order: options.order });
	const ctx = {
		hasUI: true,
		mode: "tui",
		cwd: options.cwd ?? os.tmpdir(),
		isIdle: () => options.idle ?? true,
		sessionManager: {
			getBranch: () => options.branch ?? [],
			getEntries: () => options.allEntries ?? options.branch ?? [],
			getSessionId: () => "test-session",
		},
		ui: {
			notify: (message: string, type?: string) => notifications.push({ message, type }),
			custom: async (factory: TestCustomFactory) => {
				await factory(tui, {}, {}, () => options.order?.push("done"));
			},
		},
	} as unknown as ExtensionContext;
	return { ctx, notifications };
}

test("snapshot includes current branch, partial assistant/tool text, finalized output, and deferred Bash exactly once", () => {
	const branch = [
		messageEntry("system", "system", "PRIVATE_SYSTEM_INSTRUCTIONS"),
		messageEntry("prompt", "user", [{ type: "text", text: "VISIBLE_USER_PROMPT" }]),
		messageEntry("answer", "assistant", [{ type: "text", text: "FINAL_ASSISTANT_RESPONSE" }]),
		messageEntry("tool-result", "toolResult", [{ type: "text", text: "FINAL_TOOL_RESULT" }], {
			toolCallId: "finished-tool",
			toolName: "bash",
		}),
		bashMessageEntry("bash-old", "printf repeat", "PERSISTED_BASH_OUTPUT"),
	] as SessionEntry[];
	const progress = createSessionProgress();
	progress.assistantMessages.set("partial-assistant", "UNIQUE_ASSISTANT_PROGRESS_MARKER");
	progress.assistantMessages.set("message-answer", "DUPLICATE_FINAL_ASSISTANT_MARKER");
	recordAssistantUpdate(progress, {
		id: "final-assistant-before-branch",
		role: "assistant",
		content: [{ type: "text", text: "FINALIZED_ASSISTANT_BEFORE_BRANCH_MARKER" }],
	});
	finishAssistant(progress, {
		id: "final-assistant-before-branch",
		role: "assistant",
		content: [{ type: "text", text: "FINALIZED_ASSISTANT_BEFORE_BRANCH_MARKER" }],
	});
	recordToolUpdate(progress, "partial-tool", "read", { path: "file.ts" }, {
		content: [{ type: "text", text: "UNIQUE_TOOL_PROGRESS_MARKER" }],
	});
	finishTool(progress, "finished-tool", "bash", {}, {
		content: [{ type: "text", text: "DUPLICATE_FINAL_TOOL_MARKER" }],
	}, false);
	finishTool(progress, "final-tool-before-branch", "read", { path: "other.ts" }, {
		content: [{ type: "text", text: "FINALIZED_TOOL_BEFORE_BRANCH_MARKER" }],
	}, false);
	const components = [
		fakeBash("printf repeat", ["PERSISTED_BASH_OUTPUT"], "chat"),
		fakeBash("printf repeat", ["DEFERRED_COMPLETE_BASH_MARKER"], "pending"),
	];

	const snapshot = buildConversationSnapshot(branch, progress, components);
	assert.match(snapshot, /VISIBLE_USER_PROMPT/);
	assert.match(snapshot, /FINAL_ASSISTANT_RESPONSE/);
	assert.match(snapshot, /FINAL_TOOL_RESULT/);
	assert.match(snapshot, /UNIQUE_ASSISTANT_PROGRESS_MARKER/);
	assert.match(snapshot, /FINALIZED_ASSISTANT_BEFORE_BRANCH_MARKER/);
	assert.match(snapshot, /FINALIZED_TOOL_BEFORE_BRANCH_MARKER/);
	assert.match(snapshot, /UNIQUE_TOOL_PROGRESS_MARKER/);
	assert.match(snapshot, /DEFERRED_COMPLETE_BASH_MARKER/);
	assert.equal(snapshot.match(/PERSISTED_BASH_OUTPUT/g)?.length, 1);
	assert.doesNotMatch(snapshot, /PRIVATE_SYSTEM_INSTRUCTIONS|DUPLICATE_FINAL_ASSISTANT_MARKER|DUPLICATE_FINAL_TOOL_MARKER/);
});

test("Bash reconciliation deduplicates repeated saved command/output occurrences", () => {
	const branch = [
		bashMessageEntry("first", "echo same", "IDENTICAL_SAVED_OUTPUT"),
		bashMessageEntry("second", "echo same", "IDENTICAL_SAVED_OUTPUT"),
		messageEntry("prompt", "user", "CURRENT_AGENT_PROMPT"),
	] as SessionEntry[];
	const components = [
		fakeBash("echo same", ["IDENTICAL_SAVED_OUTPUT"], "chat"),
		fakeBash("echo same", ["IDENTICAL_SAVED_OUTPUT"], "pending", "complete"),
	];
	const snapshot = buildConversationSnapshot(branch, createSessionProgress(), components);
	assert.equal(snapshot.match(/IDENTICAL_SAVED_OUTPUT/g)?.length, 3);
});

test("completed pending Bash is kept before flush but deduplicated after flush", () => {
	const command = "echo same";
	const output = "IDENTICAL_DEFERRED_OUTPUT";
	const beforeFlush = [
		bashMessageEntry("old", command, output),
		messageEntry("prompt", "user", "CURRENT_AGENT_PROMPT"),
		messageEntry("response", "assistant", "CURRENT_AGENT_RESPONSE"),
	] as SessionEntry[];
	const component = fakeBash(command, [output], "pending", "complete");

	// The old identical branch result predates this turn and must not suppress
	// the result that is still deferred while the agent is active.
	const deferredSnapshot = buildConversationSnapshot(beforeFlush, createSessionProgress(), [component]);
	assert.equal(deferredSnapshot.match(/IDENTICAL_DEFERRED_OUTPUT/g)?.length, 2);

	// Pi appends completed deferred Bash results at agent settlement, while the
	// UI component remains in pending until the next normal user input.
	const afterFlush = [...beforeFlush, bashMessageEntry("flushed", command, output)];
	const settledSnapshot = buildConversationSnapshot(afterFlush, createSessionProgress(), [component]);
	assert.equal(settledSnapshot.match(/IDENTICAL_DEFERRED_OUTPUT/g)?.length, 2);
});

test("a running repeated Bash with identical output survives compaction reconciliation", () => {
	const branch = [
		bashMessageEntry("old-one", "echo same", "IDENTICAL_BASH_OUTPUT"),
		bashMessageEntry("old-two", "echo same", "IDENTICAL_BASH_OUTPUT"),
	] as SessionEntry[];
	// Compaction removed the old chat components; only the new live component remains.
	const components = [fakeBash("echo same", ["IDENTICAL_BASH_OUTPUT"], "chat", "running")];
	const snapshot = buildConversationSnapshot(branch, createSessionProgress(), components);
	assert.equal(snapshot.match(/IDENTICAL_BASH_OUTPUT/g)?.length, 3);
	assert.match(snapshot, /Status: running/);
});

test("a chat Bash result with a repeated command but new output is not reconciled to old history", () => {
	const branch = [bashMessageEntry("old", "echo same", "OLD_BASH_OUTPUT")] as SessionEntry[];
	const components = [fakeBash("echo same", ["NEW_BASH_OUTPUT"], "chat", "complete")];
	const snapshot = buildConversationSnapshot(branch, createSessionProgress(), components);
	assert.match(snapshot, /OLD_BASH_OUTPUT/);
	assert.match(snapshot, /NEW_BASH_OUTPUT/);
});

test("a truncated saved Bash result reconciles with its full live component output", () => {
	const branch = [messageEntry("truncated", "bashExecution", "SAVED_TAIL_OUTPUT", {
		command: "printf large",
		output: "SAVED_TAIL_OUTPUT",
		truncated: true,
	})] as SessionEntry[];
	const component = fakeBash("printf large", ["OMITTED_HEAD_OUTPUT", "SAVED_TAIL_OUTPUT"], "chat", "complete");
	const snapshot = buildConversationSnapshot(branch, createSessionProgress(), [component]);
	assert.equal(snapshot.match(/SAVED_TAIL_OUTPUT/g)?.length, 1);
	assert.doesNotMatch(snapshot, /OMITTED_HEAD_OUTPUT/);
});

test("finalized assistant tool-call progress without a message id is deduplicated", () => {
	const content = [{ type: "toolCall", name: "scenario_stream_tool", arguments: {} }];
	const branch = [messageEntry("persisted-call", "assistant", content, { id: undefined })] as SessionEntry[];
	const message = { role: "assistant", content };
	const progress = createSessionProgress();
	recordAssistantUpdate(progress, message);
	finishAssistant(progress, message);

	const snapshot = buildConversationSnapshot(branch, progress);
	assert.equal(snapshot.match(/Tool call: scenario_stream_tool/g)?.length, 1);

	const partialProgress = createSessionProgress();
	recordAssistantUpdate(partialProgress, message);
	const partialSnapshot = buildConversationSnapshot(branch, partialProgress);
	assert.equal(partialSnapshot.match(/Tool call: scenario_stream_tool/g)?.length, 2);
});

test("branch switch clears in-progress state and session snapshots do not cross sessions", () => {
	const store = new Map();
	const oldBranchProgress = getSessionProgress(store, "session-old");
	recordAssistantUpdate(oldBranchProgress, {
		id: "old-partial",
		role: "assistant",
		content: [{ type: "text", text: "ABANDONED_BRANCH_PROGRESS" }],
	});
	const currentProgress = getSessionProgress(store, "session-current");
	recordAssistantUpdate(currentProgress, {
		id: "current-partial",
		role: "assistant",
		content: [{ type: "text", text: "CURRENT_BRANCH_PROGRESS" }],
	});

	clearSessionProgress(store, "session-old");
	const snapshot = buildConversationSnapshot([], store.get("session-current"));
	assert.match(snapshot, /CURRENT_BRANCH_PROGRESS/);
	assert.doesNotMatch(snapshot, /ABANDONED_BRANCH_PROGRESS/);
	assert.equal(store.has("session-old"), false);
});

test("runInspectSession reads getBranch rather than all session entries", async () => {
	const current = messageEntry("current", "user", "CURRENT_BRANCH_ONLY");
	const abandoned = messageEntry("abandoned", "user", "ABANDONED_BRANCH_ONLY");
	const { ctx } = fakeContext({ branch: [current], allEntries: [current, abandoned] });
	let opened = "";
	await runInspectSession(ctx, createSessionProgress(), {
		resolveEditorCommand: () => "test-editor",
		spawnEditor: async (_command, filePath) => {
			opened = fs.readFileSync(filePath, "utf8");
			return 0;
		},
	});
	assert.match(opened, /CURRENT_BRANCH_ONLY/);
	assert.doesNotMatch(opened, /ABANDONED_BRANCH_ONLY/);
});

test("configured project editor is used, temp file is private, and TUI resumes after editor failure", async () => {
	const root = fs.mkdtempSync(path.join(os.tmpdir(), "inspect-session-test-"));
	const projectPi = path.join(root, ".pi");
	fs.mkdirSync(projectPi);
	fs.writeFileSync(path.join(projectPi, "settings.json"), JSON.stringify({ externalEditor: "dummy-editor --wait" }));
	const order: string[] = [];
	const { ctx, notifications } = fakeContext({
		cwd: root,
		branch: [messageEntry("prompt", "user", "PRIVATE_FILE_CONTENT")],
		idle: false,
		tui: fakeTui({ order }),
		order,
	});
	let selectedCommand = "";
	let tempDirectory = "";

	try {
		await runInspectSession(ctx, createSessionProgress(), {
			spawnEditor: async (command, filePath) => {
				selectedCommand = command;
				tempDirectory = path.dirname(filePath);
				assert.equal(fs.readFileSync(filePath, "utf8").includes("PRIVATE_FILE_CONTENT"), true);
				assert.equal(fs.statSync(filePath).mode & 0o777, 0o600);
				throw new Error("dummy editor failure");
			},
		});
	} finally {
		fs.rmSync(root, { recursive: true, force: true });
	}

	assert.equal(selectedCommand, "dummy-editor --wait");
	assert.equal(fs.existsSync(tempDirectory), false);
	assert.deepEqual(order, ["stop:true", "start", "done"]);
	assert.ok(notifications.some(({ type, message }) => type === "error" && /dummy editor failure/.test(message)));
});

test("captures chat and pending Bash components from Pi's fullscreen layout", () => {
	const tui = fakeTui({
		chat: [fakeBash("printf chat", ["CHAT_BASH_MARKER"], "chat", "running")],
		pending: [fakeBash("printf pending", ["PENDING_BASH_MARKER"], "pending", "complete")],
	});
	assert.deepEqual(captureUiBashComponents(tui), [
		{ area: "chat", command: "printf chat", status: "running", outputLines: ["CHAT_BASH_MARKER"] },
		{ area: "pending", command: "printf pending", status: "complete", outputLines: ["PENDING_BASH_MARKER"] },
	]);
});

test("unsupported TUI layout fails closed before opening an editor", async () => {
	const { ctx, notifications } = fakeContext({
		tui: { mode: "regular", children: [], stop: () => {}, start: () => {} } as ReturnType<typeof fakeTui>,
	});
	let opened = false;
	await runInspectSession(ctx, createSessionProgress(), {
		resolveEditorCommand: () => "test-editor",
		spawnEditor: async () => {
			opened = true;
			return 0;
		},
	});
	assert.equal(opened, false);
	assert.ok(notifications.some(({ type, message }) => type === "error" && /Unsupported Pi TUI layout/.test(message)));
});

test("registers one Pi shortcut plus the inspect-session command", () => {
	const commands = new Map<string, unknown>();
	const shortcuts = new Map<string, unknown>();
	const handlers = new Map<string, unknown>();
	const pi = {
		on: (event: string, handler: unknown) => handlers.set(event, handler),
		registerCommand: (name: string, command: unknown) => commands.set(name, command),
		registerShortcut: (shortcut: string, handler: unknown) => shortcuts.set(shortcut, handler),
	} as unknown as ExtensionAPI;

	extension(pi);
	assert.ok(commands.has(INSPECT_SESSION_COMMAND));
	assert.deepEqual([...shortcuts.keys()], ["ctrl+alt+e"]);
	assert.equal(INSPECT_SESSION_SHORTCUT, "ctrl+alt+e");
	assert.ok(handlers.has("session_tree"));
	assert.ok(handlers.has("tool_execution_update"));
	assert.ok(handlers.has("tool_execution_end"));
});
