import assert from "node:assert/strict";
import { appendFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { execFileSync } from "node:child_process";
import { createRequire, registerHooks } from "node:module";
import { pathToFileURL } from "node:url";

// Direct Node tests need the same TUI dependency Pi supplies to extensions.
const piRequire = createRequire(join(execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim(), "@earendil-works/pi-coding-agent/package.json"));
const tuiURL = pathToFileURL(piRequire.resolve("@earendil-works/pi-tui")).href;
registerHooks({ resolve(specifier, context, nextResolve) {
	return specifier === "@earendil-works/pi-tui"
		? { url: tuiURL, shortCircuit: true }
		: nextResolve(specifier, context);
} });
const { default: standingReminder } = await import("./index.ts");
import { readTriggerConfig } from "./config.ts";

test("exact trigger configuration defaults, empty, explicit and invalid", () => {
	const root = mkdtempSync(join(tmpdir(), "reminder-config-"));
	const path = join(root, "config.json");
	try {
		assert.deepEqual([...readTriggerConfig(path).triggers], ["tool-result:ask_user_question"]);
		for (const triggers of [[], ["tool-result:subagent", "message:handoff"]]) {
			writeFileSync(path, JSON.stringify({ triggers }));
			assert.deepEqual([...readTriggerConfig(path).triggers], triggers);
		}
		for (const value of ['broken', '{}', '{"triggers":["tool-result:*"]}', '{"triggers":["message:"]}']) {
			writeFileSync(path, value);
			assert.ok(readTriggerConfig(path).warning);
			assert.equal(readTriggerConfig(path).triggers.size, 0);
		}
	} finally { rmSync(root, { recursive: true, force: true }); }
});

test("selected direct/nested/error completions coalesce; ordinary tools and UI do not refresh", async () => {
	const h = createHarness();
	try {
		await start(h);
		setEditor(h, { text: "exact\n guidance" });
		await h.command("reminder");
		const operator = await submit(h, "work");
		const initial = (await h.call("context", { messages: [operator] }) as any).messages[1];
		const result = { role: "toolResult", toolCallId: "root", timestamp: 123, content: [] };
		for (const toolName of ["read", "subagent"]) await h.call("tool_execution_end", { toolName });
		h.ctx.ui.notify("question UI only");
		const ordinary = (await h.call("context", { messages: [operator, result] }) as any).messages;
		assert.equal(ordinary.length, 3);
		assert.equal(ordinary[1], initial);
		for (const event of [{}, { parentToolCallId: "root" }, { isError: true }]) {
			await h.call("tool_execution_end", { toolName: "ask_user_question", ...event });
		}
		const refreshed = (await h.call("context", { messages: [operator, result] }) as any).messages;
		assert.equal(refreshed.length, 4);
		assert.equal(refreshed[3].content[0].text, "<standing-reminder>\nexact\n guidance\n</standing-reminder>");
		assert.deepEqual((await h.call("context", { messages: [operator, result] }) as any).messages, refreshed);
		setEditor(h, { text: "latest" }); await h.command("reminder");
		setEditor(h, { text: "final" }); await h.command("reminder");
		await h.call("tool_execution_end", { toolName: "ask_user_question" });
		const queued = await submit(h, "continue");
		const edited = (await h.call("context", { messages: [operator, result, queued] }) as any).messages;
		assert.equal(edited.length, 4);
		assert.equal(edited[3].content[0].text, "<standing-reminder>\nfinal\n</standing-reminder>");
		await h.command("reminder-clear");
		await h.call("tool_execution_end", { toolName: "ask_user_question", isError: true });
		assert.equal(await h.call("context", { messages: [operator, result, queued] }), undefined);
		assert.equal(serializedState(h).pending, false);
	} finally { h.cleanup(); }
});

test("custom selectors baseline history and occurrences across tree, compaction and startup", async () => {
	const path = new URL("./config.json", import.meta.url);
	assert.equal(existsSync(path), false, "test will not overwrite an operator config");
	const h = createHarness();
	const custom = { role: "custom", customType: "handoff", timestamp: 77, content: [] };
	try {
		writeFileSync(path, JSON.stringify({ triggers: ["message:handoff"] }));
		h.entries.push({ type: "message", message: custom });
		await start(h); setEditor(h, { text: "guide" }); await h.command("reminder");
		const operator = await submit(h, "work");
		const first = (await h.call("context", { messages: [operator, custom] }) as any).messages;
		assert.equal(first.length, 3);
		assert.deepEqual((await h.call("context", { messages: [operator, custom] }) as any).messages, first);
		const second = (await h.call("context", { messages: [operator, custom, custom] }) as any).messages;
		assert.equal(second.length, 5);
		assert.equal(second[4].content[0].text, "<standing-reminder>\nguide\n</standing-reminder>");
		h.entries.push({ type: "message", message: custom });
		await h.call("session_tree");
		assert.equal(await h.call("context", { messages: [operator, custom, custom] }), undefined);
		await h.call("session_compact");
		assert.equal(await h.call("context", { messages: [operator, custom, custom] }), undefined);
		await start(h, "resume");
		assert.equal(await h.call("context", { messages: [operator, custom, custom] }), undefined);
	} finally { rmSync(path); h.cleanup(); }
});

test("native custom_message history never refreshes an extension-only request", async () => {
	const path = new URL("./config.json", import.meta.url);
	assert.equal(existsSync(path), false, "test will not overwrite an operator config");
	const h = createHarness();
	const custom = { role: "custom", customType: "handoff", timestamp: 77, content: [] };
	try {
		writeFileSync(path, JSON.stringify({ triggers: ["message:handoff"] }));
		h.entries.push({ type: "custom_message", customType: "handoff", timestamp: new Date(77).toISOString(), content: [], display: false });
		await start(h); setEditor(h, { text: "guide" }); await h.command("reminder");
		const operator = await submit(h, "work");
		await h.call("context", { messages: [operator, custom] });
		await h.call("agent_settled");
		for (const lifecycle of ["session_start", "session_tree", "session_compact"]) {
			await h.call(lifecycle, { reason: "resume" });
			const extension = await submit(h, "extension continuation", "extension");
			assert.equal(await h.call("context", { messages: [operator, custom, extension] }), undefined, lifecycle);
			await h.call("agent_settled");
		}
	} finally { rmSync(path); h.cleanup(); }
});

test("idle warming and compaction do not consume pending saves; settlement preserves them", async () => {
	const h = createHarness();
	try {
		await start(h); setEditor(h, { text: "pending" }); await h.command("reminder");
		const operator = await submit(h, "work");
		h.ctx.isIdle = () => true;
		assert.equal(await h.call("context", { messages: [operator] }), undefined);
		assert.equal(serializedState(h).pending, true);
		await h.call("session_compact");
		await h.call("agent_settled");
		assert.equal(serializedState(h).pending, true);
		h.ctx.isIdle = () => false;
		const next = await submit(h, "next");
		assert.equal((await h.call("context", { messages: [next] }) as any).messages[1].content[0].text, "<standing-reminder>\npending\n</standing-reminder>");
		assert.equal(serializedState(h).pending, false);
	} finally { h.cleanup(); }
});
import {
	emptyReminderState,
	hasReminderMarker,
	readReminderState,
	stateFilePath,
	writeReminderState,
} from "./helpers.ts";

type Handler = (event: any, ctx: any) => unknown;

type FakeContext = {
	mode: string;
	hasUI: boolean;
	cwd: string;
	isIdle: () => boolean;
	sessionManager: {
		getSessionId: () => string;
		getSessionDir: () => string;
		getSessionFile: () => string | undefined;
		getEntries: () => any[];
		getLeafId: () => string;
		getBranch: () => any[];
		buildSessionContext: () => { messages: any[] };
	};
	ui: {
		notifications: Array<{ message: string; type?: string }>;
		widgets: Map<string, string[]>;
		tui: { stopped: number; started: number; renders: number };
		custom: (factory: (tui: any, theme: unknown, keybindings: unknown, done: (value: unknown) => void) => unknown) => Promise<unknown>;
		notify: (message: string, type?: string) => void;
		setWidget: (key: string, content: string[] | ((tui: any, theme: any) => { render: (width: number) => string[] }) | undefined) => void;
	};
};

function createHarness(id = "session-parent", sharedSessionDir?: string) {
	const root = mkdtempSync(join(tmpdir(), "standing-reminder-test-"));
	const project = join(root, "project");
	const sessionDir = sharedSessionDir ?? join(root, "sessions");
	const agentDir = join(root, "agent");
	mkdirSync(join(project, ".pi"), { recursive: true });
	mkdirSync(sessionDir, { recursive: true });
	mkdirSync(agentDir, { recursive: true });
	const sessionFile = join(sessionDir, `${id}.jsonl`);
	writeFileSync(sessionFile, `${JSON.stringify({ type: "session", version: 3, id, timestamp: new Date().toISOString(), cwd: project })}\n`);
	const entries: any[] = [];
	let entryNumber = 0;
	const handlers = new Map<string, Handler>();
	const commands = new Map<string, { handler: (args: string, ctx: any) => Promise<void> }>();
	const api = {
		on: (name: string, handler: Handler) => handlers.set(name, handler),
		registerCommand: (name: string, command: { handler: (args: string, ctx: any) => Promise<void> }) => commands.set(name, command),
		appendEntry: (customType: string, data: unknown) => {
			const entry = {
				type: "custom",
					id: `entry-${++entryNumber}`,
					parentId: entryNumber === 1 ? null : `entry-${entryNumber - 1}`,
					timestamp: new Date().toISOString(),
					customType,
					data,
			};
			entries.push(entry);
			appendFileSync(sessionFile, `${JSON.stringify(entry)}\n`);
		},
		sendUserMessage: () => assert.fail("reminder controls must not submit a user message"),
	};
	const tui = { stopped: 0, started: 0, renders: 0 };
	const notifications: Array<{ message: string; type?: string }> = [];
	const widgets = new Map<string, string[]>();
	const ctx: FakeContext = {
		mode: "tui",
		hasUI: true,
		cwd: project,
		isIdle: () => false,
		sessionManager: {
			getSessionId: () => id,
			getSessionDir: () => sessionDir,
			getSessionFile: () => sessionFile,
			getEntries: () => entries,
			getLeafId: () => "leaf-now",
			getBranch: () => entries,
			buildSessionContext: () => ({ messages: entries.flatMap((entry) =>
				entry.type === "message" ? [entry.message] : entry.type === "custom_message"
					? [{ role: "custom", customType: entry.customType, timestamp: new Date(entry.timestamp).getTime(), content: entry.content, display: entry.display }]
					: []) }),
		},
		ui: {
			notifications,
			widgets,
			tui,
			custom: async (factory) => {
				return await new Promise((resolve, reject) => {
					Promise.resolve(factory(
						{
							stop: () => tui.stopped++,
							start: () => tui.started++,
							requestRender: () => tui.renders++,
						},
						{},
						{},
						resolve,
					)).catch(reject);
				});
			},
			notify: (message, type) => notifications.push({ message, type }),
			setWidget: (key, content) => {
				if (content) widgets.set(key, typeof content === "function"
					? content({}, { fg: (color: string, text: string) => { assert.ok(color === "dim" || color === "warning" && text === "▎ ", color); return color === "dim" ? `\x1b[90m${text}\x1b[39m` : `<bar>${text}`; } }).render(200)
					: content);
				else widgets.delete(key);
			},
		},
	};
	standingReminder(api as any);
	const call = async (eventName: string, event: any = {}) => {
		const handler = handlers.get(eventName);
		assert.ok(handler, `missing ${eventName} handler`);
		return await handler(event, ctx);
	};
	const command = async (name: string) => {
		const registered = commands.get(name);
		assert.ok(registered, `missing /${name} command`);
		await registered.handler("", ctx);
	};
	const cleanup = () => rmSync(root, { recursive: true, force: true });
	return { root, project, sessionDir, agentDir, sessionFile, entries, api, ctx, handlers, commands, call, command, cleanup };
}

function setEditor(harness: ReturnType<typeof createHarness>, options: { text?: string; exitCode?: number; write?: boolean }): string {
	const editorScript = join(harness.root, "fake-editor.mjs");
	const tracePath = join(harness.root, "editor-path.txt");
	const write = options.write !== false;
	const script = [
		"import { readFileSync, writeFileSync } from 'node:fs';",
		"const draft = process.argv.at(-1);",
		...(write ? [`writeFileSync(draft, ${JSON.stringify(options.text ?? "")}, 'utf8');`] : []),
		`writeFileSync(${JSON.stringify(tracePath)}, JSON.stringify({ draft, text: readFileSync(draft, 'utf8') }));`,
		`process.exit(${options.exitCode ?? 0});`,
	].join("\n");
	writeFileSync(editorScript, script);
	writeFileSync(join(harness.project, ".pi", "settings.json"), JSON.stringify({ externalEditor: `node ${editorScript}` }));
	return tracePath;
}

async function start(harness: ReturnType<typeof createHarness>, reason = "new", previousSessionFile?: string) {
	await harness.call("session_start", { reason, previousSessionFile });
}

function userMessage(text: string) {
	return { role: "user", content: [{ type: "text", text }], timestamp: Date.now() };
}

async function submit(harness: ReturnType<typeof createHarness>, text: string, source: "interactive" | "rpc" | "extension" = "interactive") {
	const message = userMessage(text);
	await harness.call("message_start", { message, source });
	return message;
}

function serializedState(harness: ReturnType<typeof createHarness>) {
	const file = stateFilePath(harness.sessionDir, harness.ctx.sessionManager.getSessionId());
	const result = readReminderState(file);
	assert.equal(result.kind, "ok");
	return result.kind === "ok" ? result.state : emptyReminderState();
}

test("reminder widget is dim behind its coloured bar", async () => {
	const h = createHarness();
	try {
		await start(h);
		assert.equal(h.ctx.ui.widgets.get("standing-reminder")?.[0], "<bar>▎ \x1b[90mNo session reminder · /reminder to set one\x1b[39m");
	} finally { h.cleanup(); }
});

test("session state writes atomically with private permissions and validates restores", () => {
	const root = mkdtempSync(join(tmpdir(), "standing-reminder-state-test-"));
	try {
		const file = stateFilePath(root, "session/with spaces");
		const state = { reminder: "first line\n second line\tkept", pending: true };
		writeReminderState(file, state);
		assert.deepEqual(readReminderState(file), { kind: "ok", state });
		assert.equal(statSync(file).mode & 0o777, 0o600);
		assert.equal(statSync(join(root, "standing-reminder")).mode & 0o777, 0o700);
		writeFileSync(file, "not json");
		assert.equal(readReminderState(file).kind, "error");
		assert.equal(readReminderState(join(root, "missing.json")).kind, "missing");
	} finally {
		rmSync(root, { recursive: true, force: true });
	}
});

test("message_start provenance admits only known operator origins and fails closed when it is absent or unknown", async () => {
	const h = createHarness();
	try {
		await start(h);
		setEditor(h, { text: "current reminder" });
		await h.command("reminder");

		const sameTextOperator = userMessage("identical content");
		sameTextOperator.timestamp = 101;
		await h.call("message_start", { message: sameTextOperator, source: "interactive" });
		const operatorContext = await h.call("context", { messages: [sameTextOperator] }) as any;
		assert.match(operatorContext.messages[1].content[0].text, /current reminder/);

		const sameTextExtension = userMessage("identical content");
		sameTextExtension.timestamp = 202;
		await h.call("message_start", { message: sameTextExtension, source: "extension" });
		assert.equal(await h.call("context", { messages: [sameTextExtension] }), undefined);
		assert.equal(await h.call("context", {
			messages: [sameTextOperator, sameTextExtension, { role: "assistant", content: [] }, { role: "toolResult", content: [] }],
		}), undefined);

		const missingOrigin = userMessage("unattributed message");
		missingOrigin.timestamp = 303;
		await h.call("message_start", { message: missingOrigin });
		assert.equal(await h.call("context", { messages: [missingOrigin] }), undefined);

		const unknownOrigin = userMessage("future source");
		unknownOrigin.timestamp = 404;
		await h.call("message_start", { message: unknownOrigin, source: "future-source" });
		assert.equal(await h.call("context", { messages: [unknownOrigin] }), undefined);
		assert.equal(
			h.ctx.ui.notifications.filter((item) => item.type === "warning" && /known message origin/.test(item.message)).length,
			2,
		);
	} finally {
		h.cleanup();
	}
});

test("same-batch extension messages do not suppress or inherit operator projections", async () => {
	const h = createHarness();
	try {
		await start(h);
		const reminder = "one current batch reminder";
		setEditor(h, { text: reminder });
		await h.command("reminder");

		const operatorOne = userMessage("same batch text");
		const extensionMessage = userMessage("same batch text");
		const operatorTwo = userMessage("same batch text");
		operatorOne.timestamp = extensionMessage.timestamp = operatorTwo.timestamp = 505;
		await h.call("message_start", { message: operatorOne, source: "interactive" });
		await h.call("message_start", { message: extensionMessage, source: "extension" });
		await h.call("message_start", { message: operatorTwo, source: "rpc" });

		const baseMessages = [operatorOne, extensionMessage, operatorTwo];
		const firstRequest = await h.call("context", { messages: baseMessages }) as any;
		assert.equal(firstRequest.messages[0], operatorOne);
		assert.equal(firstRequest.messages[1].content[0].text, `<standing-reminder>\n${reminder}\n</standing-reminder>`);
		assert.equal(firstRequest.messages[2], extensionMessage);
		assert.equal(firstRequest.messages[3], operatorTwo);
		assert.equal(firstRequest.messages[4].content[0].text, `<standing-reminder>\n${reminder}\n</standing-reminder>`);
		assert.equal(firstRequest.messages.filter((message: any) => message.content?.[0]?.text?.includes("<standing-reminder>")).length, 2);
		assert.deepEqual(serializedState(h), { reminder, pending: false });

		const continuation = await h.call("context", {
			messages: [...baseMessages, { role: "assistant", content: [] }, { role: "toolResult", content: [] }],
		}) as any;
		assert.equal(continuation.messages.filter((message: any) => message.content?.[0]?.text?.includes("<standing-reminder>")).length, 2);

		await h.call("session_compact", {});
		assert.equal(await h.call("context", { messages: baseMessages }), undefined);
	} finally {
		h.cleanup();
	}
});

test("editor saves exact multiline text, views unchanged drafts without rewriting, and clears on an empty save", async () => {
	const h = createHarness();
	try {
		await start(h);
		const initial = "first line\n  second line\n";
		setEditor(h, { text: initial });
		await h.command("reminder");
		assert.deepEqual(serializedState(h), { reminder: initial, pending: true });
		assert.deepEqual(h.ctx.ui.tui, { stopped: 1, started: 1, renders: 1 });
		assert.match(h.ctx.ui.widgets.get("standing-reminder")?.[0] ?? "", /applies to next normal request/);

		setEditor(h, { write: false });
		await h.command("reminder");
		assert.deepEqual(serializedState(h), { reminder: initial, pending: true });
		assert.ok(h.ctx.ui.notifications.some((item) => item.message === "Reminder unchanged."));

		setEditor(h, { text: "" });
		await h.command("reminder");
		assert.deepEqual(serializedState(h), { reminder: null, pending: true });
		assert.match(h.ctx.ui.widgets.get("standing-reminder")?.[0] ?? "", /Reminder cleared/);
	} finally {
		h.cleanup();
	}
});

test("failed or canceled editor retains the old value even if its draft was written", async () => {
	const h = createHarness();
	try {
		await start(h);
		setEditor(h, { text: "saved reminder" });
		await h.command("reminder");
		const before = serializedState(h);
		setEditor(h, { text: "uncommitted replacement", exitCode: 17 });
		await h.command("reminder");
		assert.deepEqual(serializedState(h), before);
		assert.ok(h.ctx.ui.notifications.some((item) => item.type === "warning" && /canceled/.test(item.message)));
		const editorRecord = JSON.parse(readFileSync(join(h.root, "editor-path.txt"), "utf8"));
		assert.equal(editorRecord.text, "uncommitted replacement");
		assert.equal(existsSync(editorRecord.draft), false);
	} finally {
		h.cleanup();
	}
});

test("failed state persistence leaves the current value unchanged and warns", async () => {
	const h = createHarness();
	try {
		await start(h);
		writeFileSync(join(h.sessionDir, "standing-reminder"), "not a directory");
		setEditor(h, { text: "must not become active" });
		await h.command("reminder");
		assert.equal(readReminderState(stateFilePath(h.sessionDir, "session-parent")).kind, "missing");
		assert.match(h.ctx.ui.widgets.get("standing-reminder")?.[0] ?? "", /No session reminder/);
		assert.ok(h.ctx.ui.notifications.some((item) => item.type === "warning" && /Could not save/.test(item.message)));
	} finally {
		h.cleanup();
	}
});

test("operator message gets one hidden exact projection through tool continuations, not after compaction or extension follow-up", async () => {
	const h = createHarness();
	try {
		await start(h);
		const reminder = "do not normalize\n  keep spacing\tand newline";
		setEditor(h, { text: reminder });
		await h.command("reminder");

		const message = await submit(h, "operator request");
		const baseMessages = [message];
		const first = await h.call("context", { messages: baseMessages });
		assert.ok(first && Array.isArray((first as any).messages));
		const firstMessages = (first as any).messages;
		assert.equal(firstMessages[0], message);
		assert.equal(firstMessages.filter((item: any) => item.role === "user").length, 2);
		assert.equal(firstMessages[1].content[0].text, `<standing-reminder>\n${reminder}\n</standing-reminder>`);
		assert.deepEqual(serializedState(h), { reminder, pending: false });

		const continuation = await h.call("context", {
			messages: [message, { role: "assistant", content: [] }, { role: "toolResult", content: [] }],
		});
		const continuationMessages = (continuation as any).messages;
		assert.equal(continuationMessages.filter((item: any) => item.content?.[0]?.text?.includes("<standing-reminder>")).length, 1);
		assert.equal(continuationMessages[1], firstMessages[1]);

		await h.call("session_compact", {});
		assert.equal(await h.call("context", { messages: [message, { role: "assistant", content: [] }] }), undefined);
		const laterOperator = await submit(h, "next operator request");
		const afterCompaction = await h.call("context", { messages: [message, laterOperator] }) as any;
		assert.equal(afterCompaction.messages.filter((item: any) => item.content?.[0]?.text?.includes("<standing-reminder>")).length, 1);

		const generated = await submit(h, "extension follow-up", "extension");
		assert.equal(await h.call("context", { messages: [generated] }), undefined);
	} finally {
		h.cleanup();
	}
});

test("edits retire prior projections at the next continuation and queued input uses current value", async () => {
	const h = createHarness();
	try {
		await start(h);
		setEditor(h, { text: "old" });
		await h.command("reminder");

		const oldMessage = await submit(h, "first request");
		const oldProjection = (await h.call("context", { messages: [oldMessage] }) as any).messages[1];
		setEditor(h, { text: "new\nvalue" });
		await h.command("reminder");
		const oldContinuation = await h.call("context", { messages: [oldMessage, { role: "assistant", content: [] }] }) as any;
		assert.ok(!oldContinuation.messages.includes(oldProjection));
		assert.equal(oldContinuation.messages[2].content[0].text, "<standing-reminder>\nnew\nvalue\n</standing-reminder>");

		const queued = userMessage("queued request");
		await h.call("message_start", { message: queued, source: "interactive" });
		const next = await h.call("context", { messages: [oldMessage, queued] }) as any;
		assert.equal(next.messages[2].content[0].text, "<standing-reminder>\nnew\nvalue\n</standing-reminder>");
		assert.match(h.ctx.ui.widgets.get("standing-reminder")?.[0] ?? "", /Reminder: new/);
	} finally {
		h.cleanup();
	}
});

test("clear command is local, leaves a next-request cue, and does not submit a chat message", async () => {
	const h = createHarness();
	try {
		await start(h);
		setEditor(h, { text: "value" });
		await h.command("reminder");
		await h.command("reminder-clear");
		assert.deepEqual(serializedState(h), { reminder: null, pending: true });
		assert.match(h.ctx.ui.widgets.get("standing-reminder")?.[0] ?? "", /cleared.*next normal request/i);
		assert.equal(h.entries.filter((entry) => entry.type === "message").length, 0);
	} finally {
		h.cleanup();
	}
});

test("resume restores the same session while a missing marked state warns and omits stale content", async () => {
	const h = createHarness();
	try {
		await start(h);
		setEditor(h, { text: "saved for resume" });
		await h.command("reminder");
		const reloaded = createExtensionOnExistingHarness(h);
		await reloaded.call("session_start", { reason: "resume" });
		const resumed = await submit(reloaded, "after resume");
		const resumedContext = await reloaded.call("context", { messages: [resumed] }) as any;
		assert.match(resumedContext.messages[1].content[0].text, /saved for resume/);

		rmSync(stateFilePath(h.sessionDir, "session-parent"), { force: true });
		const missing = createExtensionOnExistingHarness(h);
		await missing.call("session_start", { reason: "resume" });
		assert.ok(missing.ctx.ui.notifications.some((item) => item.type === "warning" && /missing/.test(item.message)));
		const message = await submit(missing, "must not get stale content");
		assert.equal(await missing.call("context", { messages: [message] }), undefined);
	} finally {
		h.cleanup();
	}
});

function createExtensionOnExistingHarness(h: ReturnType<typeof createHarness>) {
	const handlers = new Map<string, Handler>();
	const commands = new Map<string, { handler: (args: string, ctx: any) => Promise<void> }>();
	const api = {
		on: (name: string, handler: Handler) => handlers.set(name, handler),
		registerCommand: (name: string, command: { handler: (args: string, ctx: any) => Promise<void> }) => commands.set(name, command),
		appendEntry: (customType: string, data: unknown) => {
			const entry = { type: "custom", customType, data };
			h.entries.push(entry);
			appendFileSync(h.sessionFile, `${JSON.stringify(entry)}\n`);
		},
		sendUserMessage: () => assert.fail("reminder controls must not submit a user message"),
	};
	standingReminder(api as any);
	return {
		ctx: h.ctx,
		call: async (eventName: string, event: any = {}) => {
			const handler = handlers.get(eventName);
			assert.ok(handler, `missing ${eventName} handler`);
			return await handler(event, h.ctx);
		},
		command: async (name: string) => {
			const command = commands.get(name);
			assert.ok(command, `missing /${name} command`);
			await command.handler("", h.ctx);
		},
	};
}

test("fork and clone copy the current session value by ID, then parent and child edits diverge", async () => {
	const parent = createHarness("session-parent");
	const child = createHarness("session-child", parent.sessionDir);
	try {
		await start(parent);
		setEditor(parent, { text: "current parent reminder" });
		await parent.command("reminder");

		const childFile = join(child.sessionDir, "session-child.jsonl");
		writeFileSync(childFile, `${JSON.stringify({ type: "session", version: 3, id: "session-child", timestamp: new Date().toISOString(), cwd: child.project })}\n`);
		await child.call("session_start", { reason: "fork", previousSessionFile: parent.sessionFile });
		assert.deepEqual(serializedState(child), { reminder: "current parent reminder", pending: true });
		assert.ok(hasReminderMarker(child.entries));

		setEditor(child, { text: "child-only" });
		await child.command("reminder");
		assert.deepEqual(serializedState(parent), { reminder: "current parent reminder", pending: true });
		assert.deepEqual(serializedState(child), { reminder: "child-only", pending: true });

		setEditor(parent, { text: "parent-only" });
		await parent.command("reminder");
		assert.deepEqual(serializedState(child), { reminder: "child-only", pending: true });
	} finally {
		parent.cleanup();
		child.cleanup();
	}
});

test("tree navigation keeps the one session-current value and an explicit clear takes effect at processing", async () => {
	const h = createHarness();
	try {
		await start(h);
		setEditor(h, { text: "branch-independent" });
		await h.command("reminder");
		await h.call("session_tree", { oldLeafId: "leaf-now", newLeafId: "earlier-leaf" });
		assert.deepEqual(serializedState(h), { reminder: "branch-independent", pending: true });
		await h.command("reminder-clear");
		const message = await submit(h, "after tree and clear");
		assert.equal(await h.call("context", { messages: [message] }), undefined);
		assert.deepEqual(serializedState(h), { reminder: null, pending: false });
	} finally {
		h.cleanup();
	}
});



test("RPC/JSON operator input receives the advisory without rewriting contradictory user text", async () => {
	const h = createHarness();
	try {
		await start(h);
		setEditor(h, { text: "Prefer the existing design." });
		await h.command("reminder");
		const reloaded = createExtensionOnExistingHarness(h);
		reloaded.ctx.mode = "json";
		reloaded.ctx.hasUI = false;
		await reloaded.call("session_start", { reason: "resume" });

		const prompt = "For this request, choose the opposite approach.";
		const message = userMessage(prompt);
		await reloaded.call("message_start", { message, source: "rpc" });
		const request = await reloaded.call("context", { messages: [message] }) as any;
		assert.equal(request.messages[0], message);
		assert.equal(request.messages[0].content[0].text, prompt);
		assert.match(request.messages[1].content[0].text, /Prefer the existing design\./);
		assert.deepEqual(serializedState(h), { reminder: "Prefer the existing design.", pending: false });
	} finally {
		h.cleanup();
	}
});

test("an unrelated new session starts empty and does not inherit another session's state", async () => {
	const configured = createHarness("session-with-reminder");
	const unrelated = createHarness("unrelated-session", configured.sessionDir);
	try {
		await start(configured);
		setEditor(configured, { text: "session-specific value" });
		await configured.command("reminder");
		await start(unrelated);
		assert.equal(readReminderState(stateFilePath(unrelated.sessionDir, "unrelated-session")).kind, "missing");
		const message = await submit(unrelated, "new work");
		assert.equal(await unrelated.call("context", { messages: [message] }), undefined);
	} finally {
		configured.cleanup();
		unrelated.cleanup();
	}
});

test("restore failure on corrupt state warns on stderr in print mode without blocking the request", async () => {
	const h = createHarness();
	const oldWrite = process.stderr.write;
	let stderr = "";
	try {
		await start(h);
		mkdirSync(join(h.sessionDir, "standing-reminder"), { recursive: true });
		writeFileSync(stateFilePath(h.sessionDir, "session-parent"), "{broken");
		const reloaded = createExtensionOnExistingHarness(h);
		reloaded.ctx.mode = "json";
		reloaded.ctx.hasUI = false;
		process.stderr.write = ((chunk: any, ...args: any[]) => {
			stderr += String(chunk);
			return true;
		}) as typeof process.stderr.write;
		await reloaded.call("session_start", { reason: "resume" });
		assert.match(stderr, /could not restore/i);
		const message = await submit(reloaded, "continue without reminder");
		assert.equal(await reloaded.call("context", { messages: [message] }), undefined);
	} finally {
		process.stderr.write = oldWrite;
		h.cleanup();
	}
});
