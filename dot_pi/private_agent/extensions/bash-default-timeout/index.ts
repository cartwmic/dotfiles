import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

/** Used when config.json is missing or holds anything but a positive number. */
export const FALLBACK_TIMEOUT_SECONDS = 600;

/** The default limit, in seconds, from `{ "defaultTimeoutSeconds": N }` in the file at `path`. */
export function loadDefaultTimeoutSeconds(path: string): number {
	try {
		const value = (JSON.parse(readFileSync(path, "utf8")) as { defaultTimeoutSeconds?: unknown }).defaultTimeoutSeconds;
		// Pi rejects a timeout over 2^31-1 ms, so a huge value would fail every bash call.
		return typeof value === "number" && Number.isFinite(value) && value > 0 && value <= 2_000_000 ? value : FALLBACK_TIMEOUT_SECONDS;
	} catch {
		return FALLBACK_TIMEOUT_SECONDS;
	}
}

/** What the model is told when the default limit, not its own, stopped a command. */
export const timeoutHint = (seconds: number): string =>
	`The ${seconds}-second limit is a default (this call set no timeout). If the command really needs longer, run it again with a larger \`timeout\` in seconds.`;

/**
 * A bash call that sets no `timeout` gets one, so a command that hangs (a locked 1Password prompt, a grep over a huge tree)
 * is killed with its process tree instead of holding the agent for hours. A call that sets its own timeout is left alone.
 */
export default function (pi: ExtensionAPI) {
	const seconds = loadDefaultTimeoutSeconds(join(dirname(fileURLToPath(import.meta.url)), "config.json"));
	const defaulted = new Set<string>();

	pi.on("tool_call", (event) => {
		if (event.toolName !== "bash") return;
		const input = event.input as { timeout?: number };
		if (input.timeout !== undefined) return;
		input.timeout = seconds;
		defaulted.add(event.toolCallId);
	});

	// A call another handler blocks, or that is cancelled, never reaches tool_result; do not keep its id past the turn.
	pi.on("agent_end", () => defaulted.clear());

	pi.on("tool_result", (event) => {
		if (!defaulted.delete(event.toolCallId) || !event.isError) return;
		// Pi ends the text of a timed-out call with this status and attaches no structured result. Output that merely prints the
		// words, with a nonzero exit, carries structuredContent and must not be touched (replacing content alone would drop it).
		const status = `Command timed out after ${seconds} seconds`;
		const last = event.content.at(-1);
		const timedOut = event.structuredContent === undefined && last?.type === "text" && (last.text === status || last.text.endsWith(`\n\n${status}`));
		if (!timedOut) return;
		return { content: [...event.content, { type: "text" as const, text: timeoutHint(seconds) }] };
	});
}
