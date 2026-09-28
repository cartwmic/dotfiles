import type { ExtensionAPI, ExtensionContext, InputEvent } from "@earendil-works/pi-coding-agent";
import {
	currentPaneForCaller,
	invokeOverviewReconcile,
	paneWorkspaceAtPublication,
	runSessionRecap,
	settledAssistantResponse,
} from "./helpers.ts";

interface PendingPrompt {
	callerPaneId?: string;
	paneId?: string;
	text: string;
	settled: boolean;
}

function sessionIdOf(ctx: ExtensionContext): string | undefined {
	const value = ctx.sessionManager.getSessionId();
	return typeof value === "string" && value.trim() ? value : undefined;
}

function herdrPaneId(): string | undefined {
	const value = process.env.HERDR_PANE_ID?.trim();
	return value || undefined;
}

function warn(message: string): void {
	console.warn(`[herdr-overview] ${message}`);
}

function isRealUserInput(event: InputEvent, ctx: ExtensionContext): boolean {
	return (event.source === "interactive" && ctx.mode === "tui")
		|| (event.source === "rpc" && ctx.mode === "rpc");
}

interface PublicationQueue {
	promise: Promise<void>;
}

async function storeCurrentPrompt(
	pending: PendingPrompt,
	sessionId: string,
	text: string,
	isCurrent: () => boolean,
): Promise<{ action: "continue" }> {
	const pane = await currentPaneForCaller(process.env.HERDR_SOCKET_PATH?.trim() || undefined, pending.callerPaneId);
	if (!isCurrent()) return { action: "continue" };
	pending.paneId = pane?.paneId;

	const args = ["prompt", "set", "--session-id", sessionId];
	if (pending.paneId) args.push("--pane-id", pending.paneId);
	try {
		await runSessionRecap(args, text);
	} catch {
		warn("could not store the current Pi prompt");
	}
	return { action: "continue" };
}

async function prepareAndPublish(
	pending: PendingPrompt,
	sessionId: string,
	response: ReturnType<typeof settledAssistantResponse>,
): Promise<void> {
	if (!response?.text.trim() || response.stopReason === "aborted" || response.stopReason === "error") return;

	let autoPublish: string;
	try {
		autoPublish = await runSessionRecap(["config", "auto-publish"]);
	} catch {
		warn("could not read recap auto-publish policy; run session-recap config auto-publish");
		return;
	}
	if (autoPublish === "disabled") return;
	if (autoPublish !== "enabled") {
		warn("session-recap returned an invalid auto-publish policy");
		return;
	}

	const socketPath = process.env.HERDR_SOCKET_PATH?.trim() || undefined;
	const current = await currentPaneForCaller(socketPath, pending.callerPaneId);
	if (current?.paneId !== pending.paneId) {
		const oldPaneId = pending.paneId;
		pending.paneId = current?.paneId;
		if (pending.paneId) {
			const args = ["prompt", "rekey", "--session-id", sessionId, "--pane-id", pending.paneId];
			if (oldPaneId) args.push("--from-pane-id", oldPaneId);
			try {
				await runSessionRecap(args, pending.text);
			} catch {
				warn("could not retarget the current Pi prompt after its pane moved");
			}
		}
	}

	const prepareArgs = ["prepare", "--source-id", sessionId];
	if (pending.paneId) prepareArgs.push("--pane-id", pending.paneId);

	let preparedId: string;
	try {
		preparedId = await runSessionRecap(prepareArgs, response.text);
	} catch {
		// T1 stores failed prepare attempts; a failure is not a publication or wake-up.
		warn("session-recap did not prepare a publishable Pi recap");
		return;
	}
	if (!/^[0-9a-f]{32}$/.test(preparedId)) {
		warn("session-recap returned an invalid prepared recap ID");
		return;
	}

	const workspaceId = await paneWorkspaceAtPublication(socketPath, pending.callerPaneId);
	const publishArgs = ["publish", "--prepared-id", preparedId];
	if (workspaceId) publishArgs.push("--workspace-id", workspaceId);

	let publishedId: string;
	try {
		publishedId = await runSessionRecap(publishArgs);
	} catch {
		warn("session-recap could not publish the prepared Pi recap");
		return;
	}
	if (publishedId !== preparedId) {
		warn("session-recap did not confirm the prepared Pi recap publication");
		return;
	}

	if (socketPath) {
		try {
			await invokeOverviewReconcile(socketPath);
		} catch {
			// The successful record remains durable; Herdr startup reconciliation can catch it up.
			warn("Pi recap was published, but Herdr's overview.reconcile wake-up failed");
		}
	}
}

function settlePromptAndQueuePublication(
	queue: PublicationQueue,
	pending: PendingPrompt,
	sessionId: string,
	response: ReturnType<typeof settledAssistantResponse>,
): Promise<void> {
	const promptSettlement = runSessionRecap(["prompt", "settle", "--session-id", sessionId])
		.catch(() => warn("could not mark the current prompt settled"));
	// Enqueue synchronously, before awaiting the CLI, so overlapping settled hooks
	// publish in event order even if an earlier prompt-settle process is slower.
	queue.promise = queue.promise
		.then(() => promptSettlement)
		.then(() => prepareAndPublish(pending, sessionId, response))
		.catch(() => warn("could not publish the settled Pi response"));
	return promptSettlement;
}

export function registerHerdrOverviewExtension(pi: ExtensionAPI): void {
	const pendingBySession = new Map<string, PendingPrompt>();
	const publicationQueue: PublicationQueue = { promise: Promise.resolve() };

	pi.on("session_start", () => pendingBySession.clear());
	pi.on("session_shutdown", () => pendingBySession.clear());

	pi.on("input", (event, ctx) => {
		if (!isRealUserInput(event, ctx) || !event.text.trim()) return { action: "continue" };
		const sessionId = sessionIdOf(ctx);
		if (!sessionId) return { action: "continue" };
		const text = event.text;

		const pending: PendingPrompt = {
			callerPaneId: herdrPaneId(),
			text,
			settled: false,
		};
		pendingBySession.set(sessionId, pending);

		return storeCurrentPrompt(
			pending,
			sessionId,
			text,
			() => pendingBySession.get(sessionId) === pending,
		);
	});

	pi.on("agent_settled", (_event, ctx) => {
		if (ctx.isIdle() !== true) return;

		try {
			const sessionId = sessionIdOf(ctx);
			if (!sessionId) return;
			const pending = pendingBySession.get(sessionId);
			if (!pending || pending.settled) return;
			const response = settledAssistantResponse(ctx.sessionManager.getBranch());
			// Consume this prompt before any await so duplicate settle notifications cannot prepare twice.
			pending.settled = true;
			return settlePromptAndQueuePublication(publicationQueue, pending, sessionId, response);
		} catch {
			warn("could not read the settled Pi session response");
		}
	});
}

export default function (pi: ExtensionAPI): void {
	registerHerdrOverviewExtension(pi);
}
