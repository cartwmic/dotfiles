import { dirname } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { runExternalReminderEditor, type EditorResult } from "./editor.ts";
import {
	emptyReminderState,
	hasReminderMarker,
	readReminderState,
	readSessionIdentity,
	stateFilePath,
	STATE_CUSTOM_TYPE,
	writeReminderState,
	type ReminderState,
} from "./helpers.ts";

const WIDGET_KEY = "standing-reminder";
const REMINDER_OPEN = "<standing-reminder>\n";
const REMINDER_CLOSE = "\n</standing-reminder>";

type UserMessage = {
	role: "user";
	content: Array<{ type: "text"; text: string }>;
	timestamp: number;
};

type ActiveRequest = {
	timestamp: number;
	origin: "operator" | "extension" | "unknown";
	reminder: string | null;
	revision: number;
	projection?: UserMessage;
	contextSeen: boolean;
	suppressedAfterCompaction: boolean;
};

function notify(ctx: ExtensionContext, message: string, type: "info" | "warning" | "error" = "info"): void {
	if (ctx.hasUI) ctx.ui.notify(message, type);
	else console.error(`[standing-reminder] ${message}`);
}

function preview(reminder: string): string {
	const compact = reminder.split(/\r?\n/, 1)[0]!.replace(/\s+/g, " ").trim();
	if (!compact) return "(multiline reminder)";
	return compact.length > 72 ? `${compact.slice(0, 69)}…` : compact;
}

function renderStatus(ctx: ExtensionContext, state: ReminderState, available: boolean): void {
	if (ctx.mode !== "tui" || !ctx.hasUI) return;
	let text: string;
	if (!available) {
		text = "Reminder unavailable · requests proceed without it · /reminder to replace";
	} else if (state.reminder !== null && state.pending) {
		text = `Reminder saved · applies to next request: ${preview(state.reminder)}`;
	} else if (state.reminder !== null) {
		text = `Reminder: ${preview(state.reminder)} · /reminder to edit`;
	} else if (state.pending) {
		text = "Reminder cleared · applies to next request";
	} else {
		text = "No session reminder · /reminder to set one";
	}
	ctx.ui.setWidget(WIDGET_KEY, [text], { placement: "aboveEditor" });
}

function statePath(ctx: ExtensionContext): string {
	return stateFilePath(ctx.sessionManager.getSessionDir(), ctx.sessionManager.getSessionId());
}

function persist(ctx: ExtensionContext, pi: ExtensionAPI, next: ReminderState): boolean {
	if (!ctx.sessionManager.getSessionFile()) return true;
	try {
		writeReminderState(statePath(ctx), next);
	} catch {
		notify(ctx, "Could not save the session reminder. The previous value remains active.", "warning");
		return false;
	}
	try {
		if (!hasReminderMarker(ctx.sessionManager.getEntries())) {
			pi.appendEntry(STATE_CUSTOM_TYPE, { version: 1 });
		}
	} catch {
		// The sidecar is authoritative; a later startup can restore and add the marker.
		notify(ctx, "The reminder was saved, but Pi could not record its restore marker in this session.", "warning");
	}
	return true;
}

function warnRestoreFailure(ctx: ExtensionContext, detail: string): void {
	notify(
		ctx,
		`Could not restore this session's reminder (${detail}). This request will proceed without a reminder; use /reminder to replace it.`,
		"warning",
	);
}

function rememberMarker(ctx: ExtensionContext, pi: ExtensionAPI): void {
	if (!ctx.sessionManager.getSessionFile() || hasReminderMarker(ctx.sessionManager.getEntries())) return;
	try {
		pi.appendEntry(STATE_CUSTOM_TYPE, { version: 1 });
	} catch {
		notify(ctx, "The reminder was restored, but Pi could not record its restore marker.", "warning");
	}
}

function readParentState(parentSessionFile: string):
	| { kind: "ok"; state: ReminderState }
	| { kind: "empty" }
	| { kind: "error"; detail: string } {
	const identity = readSessionIdentity(parentSessionFile);
	if (identity.kind === "error") return { kind: "error", detail: "the parent session identity is unreadable" };
	const sourcePath = stateFilePath(dirname(parentSessionFile), identity.sessionId);
	const source = readReminderState(sourcePath);
	if (source.kind === "ok") return { kind: "ok", state: source.state };
	if (source.kind === "error") return { kind: "error", detail: "the parent reminder state is unreadable" };
	if (identity.hasMarker) return { kind: "error", detail: "the parent reminder state is missing" };
	return { kind: "empty" };
}

function loadSessionState(
	ctx: ExtensionContext,
	pi: ExtensionAPI,
	event: { reason: string; previousSessionFile?: string },
): { state: ReminderState; available: boolean } {
	if (event.reason === "fork" && event.previousSessionFile) {
		const parent = readParentState(event.previousSessionFile);
		if (parent.kind === "error") {
			rememberMarker(ctx, pi);
			return { state: emptyReminderState(), available: false };
		}
		if (parent.kind === "empty") return { state: emptyReminderState(), available: true };
		if (!persist(ctx, pi, parent.state)) return { state: emptyReminderState(), available: false };
		return { state: parent.state, available: true };
	}

	const marker = hasReminderMarker(ctx.sessionManager.getEntries());
	if (!ctx.sessionManager.getSessionFile()) return { state: emptyReminderState(), available: true };
	const loaded = readReminderState(statePath(ctx));
	if (loaded.kind === "ok") {
		rememberMarker(ctx, pi);
		return { state: loaded.state, available: true };
	}
	if (loaded.kind === "error") {
		rememberMarker(ctx, pi);
		warnRestoreFailure(ctx, "saved data is unreadable");
		return { state: emptyReminderState(), available: false };
	}
	if (marker) {
		warnRestoreFailure(ctx, "saved data is missing");
		return { state: emptyReminderState(), available: false };
	}
	return { state: emptyReminderState(), available: true };
}

function makeProjection(reminder: string): UserMessage {
	return {
		role: "user",
		content: [{ type: "text", text: `${REMINDER_OPEN}${reminder}${REMINDER_CLOSE}` }],
		timestamp: Date.now(),
	};
}

function acceptEditorResult(
	ctx: ExtensionContext,
	pi: ExtensionAPI,
	result: EditorResult,
	state: ReminderState,
	available: boolean,
	onSaved: (next: ReminderState) => void,
): void {
	if (result.kind === "cancelled") {
		notify(ctx, "Reminder edit canceled; the previous value remains active.", "warning");
		return;
	}
	if (result.kind === "failed") {
		notify(ctx, "Reminder editor failed; the previous value remains active.", "warning");
		return;
	}

	const value = result.text === "" ? null : result.text;
	if (available && value === state.reminder) {
		notify(ctx, "Reminder unchanged.");
		return;
	}
	const next = { reminder: value, pending: true };
	if (!persist(ctx, pi, next)) return;
	onSaved(next);
	renderStatus(ctx, next, true);
	notify(ctx, "Reminder saved; applies to the next request.");
}

export default function standingReminder(pi: ExtensionAPI): void {
	let state = emptyReminderState();
	let available = true;
	let revision = 0;
	let activeRequests: ActiveRequest[] = [];
	let pendingInput = false;
	let continuationRequests: ActiveRequest[] = [];

	pi.on("session_start", (event, ctx) => {
		activeRequests = [];
		pendingInput = false;
		continuationRequests = [];
		revision = 0;
		const loaded = loadSessionState(ctx, pi, event);
		state = loaded.state;
		available = loaded.available;
		if (!available && event.reason === "fork") warnRestoreFailure(ctx, "the parent session could not be copied");
		renderStatus(ctx, state, available);
	});

	pi.on("session_tree", (_event, ctx) => renderStatus(ctx, state, available));

	pi.on("session_compact", () => {
		for (const request of activeRequests) {
			if (request.contextSeen) request.suppressedAfterCompaction = true;
		}
	});

	pi.on("message_start", (event, ctx) => {
		if (event.message.role !== "user") return;
		const source = (event as typeof event & { source?: unknown }).source;
		const origin = source === "interactive" || source === "rpc"
			? "operator"
			: source === "extension" ? "extension" : "unknown";
		const request: ActiveRequest = {
			timestamp: event.message.timestamp,
			origin,
			reminder: origin === "operator" && available ? state.reminder : null,
			revision,
			contextSeen: false,
			suppressedAfterCompaction: false,
		};
		if (origin === "unknown") {
			notify(ctx, "Standing reminder omitted because Pi did not expose a known message origin.", "warning");
		} else if (request.reminder !== null) {
			request.projection = makeProjection(request.reminder);
		}
		activeRequests.push(request);
		pendingInput = true;
	});

	pi.on("context", (event, ctx) => {
		if (activeRequests.length === 0) return;
		const hasNewInput = pendingInput;
		pendingInput = false;
		// Pi clones context messages; preserved timestamps pair them with the processed message events without content matching.
		const indicesByTimestamp = new Map<number, number[]>();
		for (let index = 0; index < event.messages.length; index++) {
			const message = event.messages[index];
			if (message?.role !== "user" || !Number.isFinite(message.timestamp)) continue;
			const indices = indicesByTimestamp.get(message.timestamp) ?? [];
			indices.push(index);
			indicesByTimestamp.set(message.timestamp, indices);
		}
		const requestsByTimestamp = new Map<number, ActiveRequest[]>();
		for (const request of activeRequests) {
			if (!Number.isFinite(request.timestamp)) continue;
			const requests = requestsByTimestamp.get(request.timestamp) ?? [];
			requests.push(request);
			requestsByTimestamp.set(request.timestamp, requests);
		}
		const matches: Array<{ index: number; request: ActiveRequest }> = [];
		for (const [timestamp, requests] of requestsByTimestamp) {
			const indices = indicesByTimestamp.get(timestamp) ?? [];
			const matchedCount = Math.min(indices.length, requests.length);
			for (let offset = 0; offset < matchedCount; offset++) {
				matches.push({
					index: indices[indices.length - matchedCount + offset]!,
					request: requests[requests.length - matchedCount + offset]!,
				});
			}
		}
		if (matches.length === 0) {
			if (hasNewInput) continuationRequests = [];
			return;
		}

		const newlySeen = matches.filter(({ request }) => !request.contextSeen);
		for (const { request } of newlySeen) request.contextSeen = true;
		if (hasNewInput) {
			continuationRequests = newlySeen
				.filter(({ request }) => request.origin === "operator")
				.map(({ request }) => request);
		}

		const deliveredPending = newlySeen.some(({ request }) =>
			request.origin === "operator" && available && state.pending && request.revision === revision,
		);
		if (deliveredPending) {
			state = { ...state, pending: false };
			if (!persist(ctx, pi, state)) {
				notify(ctx, "The reminder was delivered, but its delivery status could not be saved.", "warning");
			}
			renderStatus(ctx, state, available);
		}

		// New input events define this delivery boundary. On tool-only continuations,
		// reuse the already processed operator messages' projections.
		const activeContinuations = new Set(continuationRequests);
		const deliveries = (hasNewInput ? newlySeen : matches.filter(({ request }) => activeContinuations.has(request)))
			.filter(({ request }) => request.origin === "operator")
			.filter(({ request }) => !request.suppressedAfterCompaction && request.reminder !== null && request.projection);
		if (deliveries.length === 0) return;

		const messages = event.messages.slice();
		for (const { index, request } of deliveries.sort((left, right) => right.index - left.index)) {
			messages.splice(index + 1, 0, request.projection!);
		}
		return { messages };
	});

	pi.on("agent_settled", () => {
		activeRequests = [];
		pendingInput = false;
		continuationRequests = [];
	});

	pi.registerCommand("reminder", {
		description: "View or edit this session's multiline reminder in your external editor",
		handler: async (_args, ctx) => {
			if (ctx.mode !== "tui" || !ctx.hasUI) {
				notify(ctx, "Reminder editing is available in Pi's terminal UI.");
				return;
			}
			const result = await runExternalReminderEditor(ctx, available ? state.reminder ?? "" : "");
			acceptEditorResult(ctx, pi, result, state, available, (next) => {
				state = next;
				available = true;
				revision++;
			});
		},
	});

	pi.registerCommand("reminder-clear", {
		description: "Clear this session's reminder",
		handler: async (_args, ctx) => {
			if (available && state.reminder === null && !state.pending) {
				notify(ctx, "No session reminder is set.");
				return;
			}
			const next = { reminder: null, pending: true };
			if (!persist(ctx, pi, next)) return;
			state = next;
			available = true;
			revision++;
			renderStatus(ctx, state, available);
			notify(ctx, "Reminder cleared; applies to the next request.");
		},
	});
}
