import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

/** pi-response-visibility's read-only observer handle: { version: 1, snapshot() }. */
export const OBSERVER = Symbol.for("pi.response-visibility.observer.v1");
export const DEFAULT_TIMEOUT_MS = 90_000;
export const DEFAULT_MAX_RETRIES = 2;
export const POLL_MS = 1_000;
export const RETRY_TEXT = "continue";

export interface Config {
	timeoutMs: number; // 0 disables
	maxRetries: number;
	invalid: string[];
}

/** PI_ANTHROPIC_STALL_RETRY_MS (default 90000, 0 disables) and PI_ANTHROPIC_STALL_RETRY_MAX (default 2). */
export function readConfig(env: Record<string, string | undefined> = process.env): Config {
	const invalid: string[] = [];
	const read = (name: string, fallback: number): number => {
		const raw = env[name];
		if (raw === undefined || raw.trim() === "") return fallback;
		const value = Number(raw);
		if (Number.isSafeInteger(value) && value >= 0) return value;
		invalid.push(name);
		return fallback;
	};
	return { timeoutMs: read("PI_ANTHROPIC_STALL_RETRY_MS", DEFAULT_TIMEOUT_MS), maxRetries: read("PI_ANTHROPIC_STALL_RETRY_MAX", DEFAULT_MAX_RETRIES), invalid };
}

/** Milliseconds without content progress, as pi-response-visibility reports it, or null when content is flowing. */
export function contentSilenceMs(snapshot: any): number | null {
	const quiet = snapshot?.quiet;
	return quiet?.absent === "content progress" && Number.isFinite(quiet.ageMs) ? quiet.ageMs : null;
}

/**
 * When an Anthropic request shows no content progress for the configured time, abort it and send "continue",
 * which is what the owner does by hand. Pi leaves the aborted reply out of the next request, so the prompt is not
 * duplicated. At most maxRetries in a row; a completed reply or a new prompt resets the count.
 */
export default function (pi: ExtensionAPI) {
	const config = readConfig();
	let timer: ReturnType<typeof setInterval> | undefined;
	let retries = 0;
	let retryPending = false;
	let warnedMissing = false;
	const stop = () => {
		if (timer) clearInterval(timer);
		timer = undefined;
	};

	// The interval holds this request's ctx only until turn_end, agent_end or session_shutdown clears it.
	function check(ctx: ExtensionContext, handle: { snapshot(): unknown }) {
		const silent = contentSilenceMs(handle.snapshot());
		if (silent === null || silent < config.timeoutMs) return;
		stop();
		const seconds = Math.round(silent / 1000);
		if (retries >= config.maxRetries) {
			ctx.ui.notify(`Anthropic: no content progress for ${seconds}s. Retry limit (${config.maxRetries}) reached; not retrying.`, "warning");
			return;
		}
		retries++;
		retryPending = true;
		ctx.ui.notify(`Anthropic: no content progress for ${seconds}s. Aborting and sending "${RETRY_TEXT}" (retry ${retries}/${config.maxRetries}).`, "warning");
		ctx.abort();
	}

	pi.on("session_start", (_event, ctx) => {
		stop();
		retries = 0;
		retryPending = false;
		if (config.invalid.length) ctx.ui.notify(`anthropic-stall-retry: ignoring invalid ${config.invalid.join(", ")}; using defaults.`, "warning");
	});
	pi.on("session_shutdown", () => {
		stop();
		retryPending = false;
	});
	pi.on("input", (event) => {
		if (event.source !== "extension") retries = 0;
	});
	pi.on("message_end", (event) => {
		const message: any = event.message;
		if (message.role === "assistant" && message.stopReason !== "aborted" && message.stopReason !== "error") retries = 0;
	});
	pi.on("turn_start", (_event, ctx) => {
		stop();
		if (config.timeoutMs === 0 || ctx.model?.provider !== "anthropic") return;
		const handle = (globalThis as any)[OBSERVER];
		if (handle?.version !== 1 || typeof handle.snapshot !== "function") {
			if (!warnedMissing) ctx.ui.notify("anthropic-stall-retry inactive: pi-response-visibility observer handle not found.", "warning");
			warnedMissing = true;
			return;
		}
		timer = setInterval(() => check(ctx, handle), POLL_MS);
		timer.unref?.();
	});
	pi.on("turn_end", stop);
	pi.on("agent_end", stop);
	pi.on("agent_settled", (event, ctx) => {
		if (!retryPending) return;
		retryPending = false;
		// The reply finished before the abort landed: nothing to resend.
		if (!event.aborted) {
			ctx.ui.notify("Anthropic recovered before the abort; no retry sent.", "info");
			return;
		}
		if (ctx.hasPendingMessages()) return;
		pi.sendUserMessage(RETRY_TEXT);
	});
}
