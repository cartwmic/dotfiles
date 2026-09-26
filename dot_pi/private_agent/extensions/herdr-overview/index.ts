import type { ExtensionAPI, ExtensionContext, InputEvent } from "@earendil-works/pi-coding-agent";
import {
	invokeOverviewReconcile,
	paneWorkspaceAtPublication,
	runSessionRecap,
	settledAssistantResponse,
} from "./helpers.ts";

interface PendingPrompt {
	paneId?: string;
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

function storeCurrentPrompt(args: string[], text: string): Promise<{ action: "continue" }> {
	return runSessionRecap(args, text)
		.catch(() => warn("could not store the current Pi prompt"))
		.then(() => ({ action: "continue" as const }));
}

async function prepareAndPublish(
	pending: PendingPrompt,
	sessionId: string,
	response: ReturnType<typeof settledAssistantResponse>,
): Promise<void> {
	if (!response?.text.trim() || response.stopReason === "aborted" || response.stopReason === "error") return;

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

	const socketPath = process.env.HERDR_SOCKET_PATH?.trim() || undefined;
	const workspaceId = await paneWorkspaceAtPublication(socketPath, pending.paneId);
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
	return runSessionRecap(["prompt", "settle", "--session-id", sessionId])
		.catch(() => warn("could not mark the current prompt settled"))
		.then(() => {
			// Keep an older, slow recap from overwriting a newer settled response.
			queue.promise = queue.promise
				.then(() => prepareAndPublish(pending, sessionId, response))
				.catch(() => warn("could not publish the settled Pi response"));
		});
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
			paneId: herdrPaneId(),
			settled: false,
		};
		pendingBySession.set(sessionId, pending);

		const args = ["prompt", "set", "--session-id", sessionId];
		if (pending.paneId) args.push("--pane-id", pending.paneId);
		return storeCurrentPrompt(args, text);
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
