/**
 * inspect-prompt — open Pi's currently assembled system prompt in the
 * operator's external editor as a discarded snapshot.
 */
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { runInspectPrompt } from "./helpers.ts";
import {
	clearSessionProgress,
	finishAssistant,
	finishTool,
	getSessionProgress,
	recordAssistantUpdate,
	recordToolStart,
	recordToolUpdate,
	runInspectSession,
	type SessionProgress,
} from "./session.ts";

export const INSPECT_SESSION_COMMAND = "inspect-session";
export const INSPECT_SESSION_SHORTCUT = "ctrl+alt+e" as const;

export default function (pi: ExtensionAPI): void {
	const progressBySession = new Map<string, SessionProgress>();
	const progressFor = (ctx: ExtensionContext) =>
		getSessionProgress(progressBySession, ctx.sessionManager.getSessionId());

	pi.on("session_start", (_event, ctx) => {
		clearSessionProgress(progressBySession, ctx.sessionManager.getSessionId());
	});
	pi.on("session_tree", (_event, ctx) => {
		clearSessionProgress(progressBySession, ctx.sessionManager.getSessionId());
	});
	pi.on("agent_end", (_event, ctx) => {
		clearSessionProgress(progressBySession, ctx.sessionManager.getSessionId());
	});
	pi.on("message_update", (event, ctx) => {
		recordAssistantUpdate(progressFor(ctx), event.message);
	});
	pi.on("message_end", (event, ctx) => {
		finishAssistant(progressFor(ctx), event.message);
	});
	pi.on("tool_execution_start", (event, ctx) => {
		recordToolStart(progressFor(ctx), event.toolCallId, event.toolName, event.args);
	});
	pi.on("tool_execution_update", (event, ctx) => {
		recordToolUpdate(progressFor(ctx), event.toolCallId, event.toolName, event.args, event.partialResult);
	});
	pi.on("tool_execution_end", (event, ctx) => {
		finishTool(progressFor(ctx), event.toolCallId, event.toolName, event.args, event.result, event.isError);
	});

	pi.registerCommand("inspect-prompt", {
		description: "Open the assembled system prompt in your external editor (snapshot; edits are discarded)",
		handler: async (_args, ctx) => {
			await runInspectPrompt(ctx);
		},
	});

	const inspectSession = async (ctx: ExtensionContext) => {
		await runInspectSession(ctx, progressFor(ctx));
	};
	pi.registerCommand(INSPECT_SESSION_COMMAND, {
		description: "Open the current conversation snapshot in your external editor",
		handler: async (_args, ctx) => {
			await inspectSession(ctx);
		},
	});
	pi.registerShortcut(INSPECT_SESSION_SHORTCUT, {
		description: "Open the current conversation snapshot in your external editor",
		handler: inspectSession,
	});
}

export { readConfiguredEditor, resolveEditorCommand, runInspectPrompt, shouldOpenEditor } from "./helpers.ts";
