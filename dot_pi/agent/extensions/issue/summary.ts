/**
 * Checkpoint-summary support for `/issue sync` (no-args form).
 *
 * Pure helpers (transcript extraction, prompt building, `pi --list-models`
 * parsing) + a thin `pi -p` print-mode invocation. The summary model runs in
 * an isolated child pi (extensions / prompt-templates / skills / context-files
 * / tools all disabled, ephemeral session) so it never re-loads this extension
 * or recurses. Everything here is agent-independent and unit-tested offline.
 */
import { spawn } from "node:child_process";

// ---------------------------------------------------------------------------
// Model catalog (`pi --list-models`)
// ---------------------------------------------------------------------------

const CATALOG_TIMEOUT_MS = 60_000;
const SUMMARY_TIMEOUT_MS = 180_000;
const KILL_GRACE_MS = 2_000;

export type CatalogFetchResult =
	| { ok: true; catalog: string[] }
	| { ok: false; error: string };

export interface RunResult {
	status: number | null;
	stdout: string;
	stderr: string;
	error?: Error;
}

/**
 * Async child runner: streams `input` on stdin, collects stdout/stderr, and
 * enforces an abortable deadline (SIGTERM then SIGKILL). Async so the pi TUI
 * event loop is never blocked while a child pi produces a summary. Injectable
 * for offline tests.
 */
export type SpawnLike = (
	cmd: string,
	args: string[],
	opts: { timeoutMs: number; input?: string },
) => Promise<RunResult>;

export function defaultAsyncSpawn(
	cmd: string,
	args: string[],
	opts: { timeoutMs: number; input?: string },
): Promise<RunResult> {
	return new Promise<RunResult>((resolve) => {
		const outChunks: Buffer[] = [];
		const errChunks: Buffer[] = [];
		// Accumulate raw bytes and decode once at the end so a multibyte UTF-8 char
		// split across two chunks isn't corrupted.
		const decode = (chunks: Buffer[]) => Buffer.concat(chunks).toString("utf8");
		let timedOut = false;
		let settled = false;
		let timer: ReturnType<typeof setTimeout> | undefined;
		let killTimer: ReturnType<typeof setTimeout> | undefined;
		const done = (r: Omit<RunResult, "stdout" | "stderr">) => {
			if (settled) return;
			settled = true;
			if (timer) clearTimeout(timer);
			if (killTimer) clearTimeout(killTimer);
			resolve({ ...r, stdout: decode(outChunks), stderr: decode(errChunks) });
		};
		let child: ReturnType<typeof spawn>;
		try {
			child = spawn(cmd, args, { stdio: ["pipe", "pipe", "pipe"] });
		} catch (e) {
			done({ status: null, error: e instanceof Error ? e : new Error(String(e)) });
			return;
		}
		timer = setTimeout(() => {
			timedOut = true;
			child.kill("SIGTERM");
			killTimer = setTimeout(() => child.kill("SIGKILL"), KILL_GRACE_MS);
			killTimer.unref?.();
		}, opts.timeoutMs);
		timer.unref?.();
		child.stdout?.on("data", (d: Buffer) => outChunks.push(Buffer.from(d)));
		child.stderr?.on("data", (d: Buffer) => errChunks.push(Buffer.from(d)));
		child.on("error", (error) => done({ status: null, error }));
		child.on("close", (status) => {
			done({
				status,
				error: timedOut ? new Error(`timed out after ${opts.timeoutMs}ms`) : undefined,
			});
		});
		if (opts.input != null && child.stdin) {
			child.stdin.on("error", () => {
				/* ignore EPIPE if the child exits before consuming stdin */
			});
			child.stdin.write(opts.input);
			child.stdin.end();
		}
	});
}

/** Parse columnar `pi --list-models` stdout → `provider/id` strings. */
export function parseListModelsOutput(stdout: string): string[] {
	const ids: string[] = [];
	for (const line of (stdout ?? "").split(/\r?\n/)) {
		const trimmed = line.trim();
		if (!trimmed) continue;
		const parts = trimmed.split(/\s+/);
		if (parts.length < 2) continue;
		if (parts[0]!.toLowerCase() === "provider") continue;
		ids.push(`${parts[0]}/${parts[1]}`);
	}
	return ids;
}

/** Case-insensitive substring filter (matches the pi builtin picker feel). */
export function filterCatalog(catalog: string[], filter: string): string[] {
	const f = filter.trim().toLowerCase();
	if (!f) return catalog.slice();
	return catalog.filter((id) => id.toLowerCase().includes(f));
}

/** Fetch + parse the model catalog. Async (non-blocking). Injectable spawn. */
export async function fetchModelsCatalog(
	spawnFn: SpawnLike = defaultAsyncSpawn,
	opts?: { piCmd?: string; timeoutMs?: number },
): Promise<CatalogFetchResult> {
	const piCmd = opts?.piCmd ?? process.env.PI_ISSUE_PI_CMD ?? "pi";
	const timeoutMs = opts?.timeoutMs ?? CATALOG_TIMEOUT_MS;
	try {
		const r = await spawnFn(piCmd, ["--list-models"], { timeoutMs });
		if (r.error) return { ok: false, error: `failed to run ${piCmd} --list-models: ${r.error.message}` };
		if ((r.status ?? 1) !== 0) {
			const detail = `${r.stderr ?? ""}${r.stdout ?? ""}`.trim();
			return { ok: false, error: detail || `pi --list-models exited ${r.status ?? "non-zero"}` };
		}
		const catalog = parseListModelsOutput(r.stdout ?? "");
		if (catalog.length === 0) return { ok: false, error: "pi --list-models produced no models" };
		return { ok: true, catalog };
	} catch (e: unknown) {
		return { ok: false, error: `failed to run ${piCmd} --list-models: ${e instanceof Error ? e.message : String(e)}` };
	}
}

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
 * silently skipping the span (Decision 2: nothing lost).
 *
 * Includes everything in the session context that evidences progress — user
 * and assistant text, assistant tool calls, and tool results (marked on error).
 * Thinking blocks are excluded (internal reasoning, not work product). No size
 * bound: the whole since-last-checkpoint span is sent.
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
// Prompt + invocation
// ---------------------------------------------------------------------------

/** Build the checkpoint-summary prompt from the bound issue intent + transcript. */
export function buildSummaryPrompt(
	issue: { displayKey: string; title: string; body?: string },
	transcript: string,
): string {
	const intent = [
		`[${issue.displayKey}] ${issue.title}`,
		issue.body ? issue.body.trim() : "",
	]
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

export type SummaryResult = { ok: true; text: string } | { ok: false; error: string };

/**
 * Run a summary through an isolated child `pi -p`. Prompt is piped on stdin
 * (avoids ARG_MAX with large transcripts). Async (non-blocking) with an
 * abortable deadline. Injectable spawn for tests.
 */
export async function runPiSummary(
	model: string,
	prompt: string,
	spawnFn: SpawnLike = defaultAsyncSpawn,
	opts?: { piCmd?: string; timeoutMs?: number },
): Promise<SummaryResult> {
	const piCmd = opts?.piCmd ?? process.env.PI_ISSUE_PI_CMD ?? "pi";
	const timeoutMs = opts?.timeoutMs ?? SUMMARY_TIMEOUT_MS;
	// -ne/-np/-ns/-nc/-nt: no extensions, prompt-templates, skills, context
	// files, or tools. --no-session: ephemeral (never pollutes session list).
	const args = ["-p", "-ne", "-np", "-ns", "-nc", "-nt", "--no-session", "--model", model];
	try {
		const r = await spawnFn(piCmd, args, { timeoutMs, input: prompt });
		if (r.error) return { ok: false, error: `failed to run ${piCmd}: ${r.error.message}` };
		if ((r.status ?? 1) !== 0) {
			const detail = `${r.stderr ?? ""}`.trim();
			return { ok: false, error: detail || `pi exited ${r.status ?? "non-zero"}` };
		}
		const text = (r.stdout ?? "").trim();
		if (!text) return { ok: false, error: "pi produced no summary output" };
		return { ok: true, text };
	} catch (e: unknown) {
		return { ok: false, error: `failed to run ${piCmd}: ${e instanceof Error ? e.message : String(e)}` };
	}
}
