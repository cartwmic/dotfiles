import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { ExtensionContext, SessionEntry } from "@earendil-works/pi-coding-agent";
import { defaultSpawnEditor, readConfiguredEditor, resolveEditorCommand } from "./helpers.ts";

type RecordValue = Record<string, unknown>;

export type BashComponentSnapshot = {
	area: "chat" | "pending";
	command: string;
	status: string;
	outputLines: string[];
	exitCode?: number;
};

export type PartialToolSnapshot = {
	toolName: string;
	args: unknown;
	output: string;
	complete?: boolean;
	isError?: boolean;
};

export type SessionProgress = {
	assistantMessages: Map<string, string>;
	finalizedAssistantMessages: Set<string>;
	toolUpdates: Map<string, PartialToolSnapshot>;
};

export function createSessionProgress(): SessionProgress {
	return {
		assistantMessages: new Map(),
		finalizedAssistantMessages: new Set(),
		toolUpdates: new Map(),
	};
}

export function getSessionProgress(
	progressBySession: Map<string, SessionProgress>,
	sessionId: string,
): SessionProgress {
	let progress = progressBySession.get(sessionId);
	if (!progress) {
		progress = createSessionProgress();
		progressBySession.set(sessionId, progress);
	}
	return progress;
}

export function clearSessionProgress(
	progressBySession: Map<string, SessionProgress>,
	sessionId?: string,
): void {
	if (sessionId === undefined) progressBySession.clear();
	else progressBySession.delete(sessionId);
}

export function recordAssistantUpdate(progress: SessionProgress, message: unknown): void {
	const value = record(message);
	if (!value || value.role !== "assistant") return;
	const id = typeof value.id === "string" ? value.id : "__current_assistant__";
	progress.assistantMessages.set(id, contentText(value.content));
	progress.finalizedAssistantMessages.delete(id);
}

export function finishAssistant(progress: SessionProgress, message: unknown): void {
	const value = record(message);
	if (value?.role !== "assistant") return;
	const id = typeof value.id === "string" ? value.id : "__current_assistant__";
	if (!progress.assistantMessages.has(id)) {
		progress.assistantMessages.set(id, contentText(value.content));
	}
	progress.finalizedAssistantMessages.add(id);
}

export function recordToolStart(
	progress: SessionProgress,
	toolCallId: string,
	toolName: string,
	args: unknown,
): void {
	progress.toolUpdates.set(toolCallId, { toolName, args, output: "", complete: false });
}

export function recordToolUpdate(
	progress: SessionProgress,
	toolCallId: string,
	toolName: string,
	args: unknown,
	partialResult: unknown,
): void {
	const result = record(partialResult);
	const output = result ? contentText(result.content) : contentText(partialResult);
	progress.toolUpdates.set(toolCallId, { toolName, args, output, complete: false });
}

export function finishTool(
	progress: SessionProgress,
	toolCallId: string,
	toolName: string,
	args: unknown,
	result: unknown,
	isError: boolean,
): void {
	const previous = progress.toolUpdates.get(toolCallId);
	const value = record(result);
	const finalOutput = value ? contentText(value.content) : contentText(result);
	progress.toolUpdates.set(toolCallId, {
		toolName,
		args,
		output: finalOutput || previous?.output || "",
		complete: true,
		isError,
	});
}

function record(value: unknown): RecordValue | undefined {
	return typeof value === "object" && value !== null ? (value as RecordValue) : undefined;
}

function json(value: unknown): string {
	try {
		return JSON.stringify(value, null, 2) ?? String(value);
	} catch {
		return String(value);
	}
}

function contentText(content: unknown): string {
	if (typeof content === "string") return content;
	if (!Array.isArray(content)) return "";
	const parts: string[] = [];
	for (const item of content) {
		const block = record(item);
		if (!block) continue;
		switch (block.type) {
			case "text":
				if (typeof block.text === "string") parts.push(block.text);
				break;
			case "image":
				parts.push("[image attached]");
				break;
			case "toolCall":
				parts.push(
					`Tool call: ${String(block.name ?? "unknown")}\nArguments:\n${json(block.arguments ?? {})}`,
				);
				break;
			case "thinking":
			case "redactedThinking":
				// Internal reasoning is not conversation text shown to the reader.
				break;
			default:
				parts.push(`[${String(block.type ?? "non-text")} content]`);
		}
	}
	return parts.join("\n");
}

function messageText(message: RecordValue): string {
	const role = message.role;
	if (role === "system" || role === "branchSummary") return "";
	if (role === "bashExecution") {
		const command = typeof message.command === "string" ? message.command : "(unknown command)";
		const contextNote = message.excludeFromContext === true ? " (excluded from model context)" : "";
		const output = typeof message.output === "string" && message.output.length > 0 ? message.output : "(no output)";
		const status = message.cancelled === true
			? "cancelled"
			: typeof message.exitCode === "number"
				? `exit ${message.exitCode}`
				: "finished";
		return `## User Bash: ${command}${contextNote}\nStatus: ${status}${message.truncated === true ? " (output truncated)" : ""}\n\n${output}`;
	}
	if (role === "custom" && message.display === false) return "";
	if (!["user", "assistant", "toolResult", "custom", "compactionSummary"].includes(String(role))) return "";

	const heading = role === "toolResult"
		? `Tool result${typeof message.toolName === "string" ? ` (${message.toolName})` : ""}`
		: role === "custom"
			? `Extension message${typeof message.customType === "string" ? ` (${message.customType})` : ""}`
			: role === "compactionSummary"
				? "Compaction summary"
				: String(role).replace(/^./, (character) => character.toUpperCase());
	const content = role === "compactionSummary" && typeof message.summary === "string"
		? message.summary
		: contentText(message.content);
	return content.length > 0 ? `## ${heading}\n\n${content}` : `## ${heading}\n\n[no visible text]`;
}

function entryMessage(entry: SessionEntry): RecordValue | undefined {
	if (entry.type !== "message") return undefined;
	return record(entry.message);
}

function normalizeBashOutput(output: string): string {
	return output.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
}

function branchBashResult(
	message: RecordValue,
): { command: string; output: string; truncated: boolean } | undefined {
	if (message.role !== "bashExecution" || typeof message.command !== "string") return undefined;
	const output = typeof message.output === "string" ? message.output : "";
	return { command: message.command, output: normalizeBashOutput(output), truncated: message.truncated === true };
}

function finalizedToolResultIds(entries: readonly SessionEntry[]): Set<string> {
	const ids = new Set<string>();
	for (const entry of entries) {
		const message = entryMessage(entry);
		if (message?.role === "toolResult" && typeof message.toolCallId === "string") {
			ids.add(message.toolCallId);
		}
	}
	return ids;
}

function unpersistedUiBash(
	entries: readonly SessionEntry[],
	components: readonly BashComponentSnapshot[],
): BashComponentSnapshot[] {
	const persisted: Array<{ command: string; output: string; truncated: boolean; entryIndex: number }> = [];
	let latestUserEntryIndex = -1;
	for (let entryIndex = 0; entryIndex < entries.length; entryIndex++) {
		const message = entryMessage(entries[entryIndex]);
		if (message?.role === "user") latestUserEntryIndex = entryIndex;
		const saved = message && branchBashResult(message);
		if (saved) persisted.push({ ...saved, entryIndex });
	}
	const matched = new Set<number>();

	const unpersisted: BashComponentSnapshot[] = [];
	for (const component of components) {
		// Running components have not been persisted yet. Older matching results
		// can remain in the branch after compaction, so keep the live output.
		if (component.status === "running") {
			unpersisted.push(component);
			continue;
		}

		const output = normalizeBashOutput(component.outputLines.join("\n"));
		const matchIndex = persisted.findIndex((saved, index) =>
			!matched.has(index) &&
			(component.area !== "pending" || (latestUserEntryIndex >= 0 && saved.entryIndex > latestUserEntryIndex)) &&
			saved.command === component.command &&
			(saved.output === output || (saved.truncated && saved.output.length > 0 && output.endsWith(saved.output))),
		);
		if (matchIndex === -1) unpersisted.push(component);
		else matched.add(matchIndex);
	}
	return unpersisted;
}

function formatUiBash(component: BashComponentSnapshot): string {
	const output = component.outputLines.length > 0 ? component.outputLines.join("\n") : "(no output yet)";
	const exit = typeof component.exitCode === "number" ? `; exit ${component.exitCode}` : "";
	return `## User Bash: ${component.command}\nStatus: ${component.status}${exit}\n\n${output}`;
}

export function buildConversationSnapshot(
	entries: readonly SessionEntry[],
	progress: SessionProgress = createSessionProgress(),
	bashComponents: readonly BashComponentSnapshot[] = [],
): string {
	const sections = ["# Current Pi conversation snapshot", ""];
	const finalizedMessageIds = new Set<string>();
	const finalizedAssistantTexts = new Set<string>();
	const toolResultIds = finalizedToolResultIds(entries);

	for (const entry of entries) {
		if (entry.type === "message") {
			const message = record(entry.message);
			if (!message) continue;
			if (typeof message.id === "string") finalizedMessageIds.add(message.id);
			if (message.role === "assistant") finalizedAssistantTexts.add(contentText(message.content));
			const rendered = messageText(message);
			if (rendered) sections.push(rendered, "");
		} else if (entry.type === "compaction" && typeof entry.summary === "string") {
			sections.push(`## Compaction summary\n\n${entry.summary}`, "");
		} else if (entry.type === "custom_message" && entry.display) {
			const rendered = messageText({
				role: "custom",
				customType: entry.customType,
				content: entry.content,
				display: entry.display,
			});
			if (rendered) sections.push(rendered, "");
		}
	}

	for (const [id, text] of progress.assistantMessages) {
		const alreadyFinalized = finalizedMessageIds.has(id) ||
			(progress.finalizedAssistantMessages.has(id) && finalizedAssistantTexts.has(text));
		if (!alreadyFinalized && text.length > 0) {
			const state = progress.finalizedAssistantMessages.has(id) ? "finalized" : "in progress";
			sections.push(`## Assistant (${state})`, "", text, "");
		}
	}

	for (const [toolCallId, tool] of progress.toolUpdates) {
		if (toolResultIds.has(toolCallId)) continue;
		const args = tool.args === undefined ? "" : `\nArguments:\n${json(tool.args)}`;
		const state = tool.complete ? "complete" : "in progress";
		const error = tool.isError ? " (error)" : "";
		sections.push(
			`## Tool output (${state}${error}): ${tool.toolName}${args}`,
			"",
			tool.output || (tool.complete ? "(no text output)" : "(waiting for output)"),
			"",
		);
	}

	for (const component of unpersistedUiBash(entries, bashComponents)) {
		sections.push(formatUiBash(component), "");
	}

	return sections.join("\n").trimEnd() + "\n";
}

function componentChildren(value: unknown): unknown[] | undefined {
	const object = record(value);
	return object && Array.isArray(object.children) ? object.children : undefined;
}

function componentName(value: unknown): string | undefined {
	const object = record(value);
	const constructor = object?.constructor;
	if (typeof constructor === "function") return constructor.name;
	const descriptor = record(constructor);
	return typeof descriptor?.name === "string" ? descriptor.name : undefined;
}

function isContainer(value: unknown): boolean {
	return componentName(value) === "Container" && componentChildren(value) !== undefined;
}

export function captureUiBashComponents(tui: unknown): BashComponentSnapshot[] {
	// Pi 0.87.1 fullscreen renders root[0] as document, root[1] as pending,
	// and document[2] as chat. Fail closed if this private layout changes.
	const tuiRecord = record(tui);
	const roots = componentChildren(tui);
	if (
		tuiRecord?.mode !== "fullscreen" ||
		!roots ||
		roots.length !== 7 ||
		!isContainer(roots[0]) ||
		!isContainer(roots[1])
	) {
		throw new Error("Unsupported Pi TUI layout; conversation snapshot stopped before opening the editor.");
	}

	const documentChildren = componentChildren(roots[0]);
	const pendingChildren = componentChildren(roots[1]);
	if (
		!documentChildren ||
		documentChildren.length !== 3 ||
		!isContainer(documentChildren[2]) ||
		!pendingChildren
	) {
		throw new Error("Unsupported Pi chat/pending layout; conversation snapshot stopped before opening the editor.");
	}

	const areas: Array<{ area: BashComponentSnapshot["area"]; children: unknown[] }> = [
		{ area: "chat", children: componentChildren(documentChildren[2]) ?? [] },
		{ area: "pending", children: pendingChildren },
	];
	const snapshots: BashComponentSnapshot[] = [];
	for (const { area, children } of areas) {
		for (const component of children) {
			const name = componentName(component);
			const object = record(component);
			if (name !== "BashExecutionComponent") {
				if (name?.startsWith("BashExecution")) {
					throw new Error("Unsupported Pi Bash component; conversation snapshot stopped before opening the editor.");
				}
				continue;
			}
			if (
				!object ||
				typeof object.command !== "string" ||
				typeof object.status !== "string" ||
				!Array.isArray(object.outputLines) ||
				!object.outputLines.every((line) => typeof line === "string")
			) {
				throw new Error("Unsupported Pi Bash component data; conversation snapshot stopped before opening the editor.");
			}
			snapshots.push({
				area,
				command: object.command,
				status: object.status,
				outputLines: [...object.outputLines],
				...(typeof object.exitCode === "number" ? { exitCode: object.exitCode } : {}),
			});
		}
	}
	return snapshots;
}

export type SessionSnapshotDependencies = {
	resolveEditorCommand?: () => string;
	spawnEditor?: (command: string, filePath: string) => Promise<number | null>;
	mkdtempSync?: typeof mkdtempSync;
	writeFileSync?: typeof writeFileSync;
	rmSync?: typeof rmSync;
};

export async function runInspectSession(
	ctx: ExtensionContext,
	progress: SessionProgress = createSessionProgress(),
	deps: SessionSnapshotDependencies = {},
): Promise<void> {
	if (!ctx.hasUI || ctx.mode !== "tui" || typeof ctx.ui.custom !== "function") {
		if (ctx.hasUI) ctx.ui.notify("inspect-session is available in Pi's interactive TUI.", "info");
		return;
	}

	const command = (deps.resolveEditorCommand ?? (() =>
		resolveEditorCommand({ configuredEditor: readConfiguredEditor({ cwd: ctx.cwd }) })))();
	const spawnEditor = deps.spawnEditor ?? defaultSpawnEditor;
	const makeTemp = deps.mkdtempSync ?? mkdtempSync;
	const write = deps.writeFileSync ?? writeFileSync;
	const remove = deps.rmSync ?? rmSync;

	try {
		await ctx.ui.custom<void>(async (tui, _theme, _keybindings, done) => {
			let directory: string | undefined;
			let stopped = false;
			try {
				// Read the active branch and both live Bash areas synchronously before releasing the terminal.
				const branch = ctx.sessionManager.getBranch();
				const liveBash = captureUiBashComponents(tui);
				const snapshot = buildConversationSnapshot(branch, progress, liveBash);
				const filePath = (() => {
					directory = makeTemp(join(tmpdir(), "pi-inspect-session-"));
					return join(directory, "conversation.md");
				})();
				write(filePath, snapshot, { encoding: "utf-8", mode: 0o600 });

				stopped = true;
				tui.stop({ preserveScreen: tui.mode === "fullscreen" });
				const exitCode = await spawnEditor(command, filePath);
				if (exitCode !== 0) throw new Error(`Editor exited with ${exitCode ?? "an error"}.`);
			} finally {
				if (directory) {
					try {
						remove(directory, { recursive: true, force: true });
					} catch {
						// Best-effort cleanup if the filesystem refuses removal.
					}
				}
				try {
					if (stopped) tui.start();
				} finally {
					done(undefined);
				}
			}
			return { render: () => [] };
		});
		ctx.ui.notify("Opened current conversation snapshot; editor changes are not applied.", "info");
	} catch (error) {
		const message = error instanceof Error ? error.message : String(error);
		ctx.ui.notify(`Could not open conversation snapshot: ${message}`, "error");
	}
}
