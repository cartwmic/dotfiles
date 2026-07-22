/**
 * Pure helpers for `/issue sync` checkpoint summaries and `/issue create`
 * drafts: session-transcript extraction and prompt building. The model call
 * itself runs in-process against the current session model (see runModel in
 * index.ts) — there is no child process here, so everything in this module is
 * agent-independent and unit-tested offline.
 */

// ---------------------------------------------------------------------------
// Transcript extraction
// ---------------------------------------------------------------------------

/** Id of the last entry in a snapshot (the checkpoint cursor), or null. */
export function lastEntryId(entries: unknown[]): string | null {
	const arr = Array.isArray(entries) ? entries : [];
	if (arr.length === 0) return null;
	const last = arr[arr.length - 1] as { id?: unknown };
	return typeof last?.id === "string" ? last.id : null;
}

/** Join the text parts of a message content value (string or part array). */
function textOfContent(content: unknown): string {
	const parts =
		typeof content === "string"
			? [{ type: "text", text: content }]
			: Array.isArray(content)
				? content
				: [];
	return parts
		.filter((c: unknown) => (c as { type?: string })?.type === "text")
		.map((c: unknown) => (c as { text?: string }).text ?? "")
		.join("\n")
		.trim();
}

/** Compact one-line render of tool-call arguments (best effort). */
function renderArgs(args: unknown): string {
	if (args == null || (typeof args === "object" && Object.keys(args).length === 0)) return "";
	try {
		return JSON.stringify(args);
	} catch {
		return String(args);
	}
}

/**
 * Serialize message entries positioned AFTER the entry whose id is `afterId`
 * (all entries when `afterId` is null). Position-based anchoring (not
 * wall-clock) means no entry is ever double-counted at an equal millisecond or
 * skipped by clock skew / a missing timestamp. When `afterId` is not found
 * (e.g. compacted away) we fail OPEN and include everything rather than risk
 * silently skipping the span.
 *
 * Includes everything in the session context that evidences progress — user
 * and assistant text, assistant tool calls, and tool results (marked on error),
 * interleaved in encountered order. Thinking blocks are excluded (internal
 * reasoning, not work product). No size bound: the whole span is sent.
 */
export function extractTranscriptAfter(entries: unknown[], afterId: string | null): string {
	const arr = Array.isArray(entries) ? entries : [];
	let start = 0;
	if (afterId != null) {
		const idx = arr.findIndex((e) => (e as { id?: unknown })?.id === afterId);
		start = idx >= 0 ? idx + 1 : 0; // not found -> include all (safe)
	}
	const chunks: string[] = [];
	for (let i = start; i < arr.length; i++) {
		const e = arr[i] as { type?: string; message?: unknown };
		if (e?.type !== "message") continue;
		const msg = e.message as { role?: string; content?: unknown } | undefined;
		if (!msg) continue;
		if (msg.role === "user") {
			const text = textOfContent(msg.content);
			if (text) chunks.push(`USER: ${text}`);
		} else if (msg.role === "assistant") {
			const parts = Array.isArray(msg.content) ? msg.content : [];
			// Iterate parts once in array order so text and tool calls stay
			// interleaved as they actually occurred; consecutive text parts are
			// coalesced and flushed at each tool-call boundary.
			let buf: string[] = [];
			const flush = () => {
				const t = buf.join("\n").trim();
				if (t) chunks.push(`ASSISTANT: ${t}`);
				buf = [];
			};
			for (const c of parts) {
				const part = c as { type?: string; name?: string; arguments?: unknown; text?: string };
				if (part?.type === "text") {
					buf.push(part.text ?? "");
				} else if (part?.type === "toolCall") {
					flush();
					const args = renderArgs(part.arguments);
					chunks.push(`ASSISTANT [tool call: ${part.name ?? "?"}${args ? ` ${args}` : ""}]`);
				}
			}
			flush();
		} else if (msg.role === "toolResult") {
			const tr = msg as { toolName?: string; content?: unknown; isError?: boolean };
			const text = textOfContent(tr.content);
			const tag = tr.isError ? " (error)" : "";
			chunks.push(`TOOL RESULT ${tr.toolName ?? "?"}${tag}: ${text || "(no text output)"}`);
		}
	}
	return chunks.join("\n\n").trim();
}

// ---------------------------------------------------------------------------
// Prompt building
// ---------------------------------------------------------------------------

/** Build the checkpoint-summary prompt from the bound issue intent + transcript. */
export function buildSummaryPrompt(
	issue: { displayKey: string; title: string; body?: string },
	transcript: string,
): string {
	const intent = [`[${issue.displayKey}] ${issue.title}`, issue.body ? issue.body.trim() : ""]
		.filter(Boolean)
		.join("\n");
	return [
		"You are writing a concise progress checkpoint comment for an issue tracker.",
		"Summarize what this coding session accomplished, framed against the issue's",
		"intent (title + description) below. Report concrete progress, decisions made,",
		"and any blockers. Ground every statement in the transcript — do NOT invent",
		"details that are not present. Output ONLY the comment body as plain text: no",
		"preamble, no markdown headers, no sign-off.",
		"",
		"ISSUE INTENT:",
		intent || "(no intent available)",
		"",
		"SESSION TRANSCRIPT (since last checkpoint):",
		transcript || "(no session activity captured)",
	].join("\n");
}
