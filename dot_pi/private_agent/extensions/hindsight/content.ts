/**
 * Content helpers for the hindsight extension: tag derivation, recall query
 * building, memory-block formatting, feedback-loop stripping, and transcript
 * serialization. Only deriveProjectTag reads the filesystem (to find the repo).
 */
import * as fs from "node:fs";
import * as path from "node:path";

export const MEMORY_OPEN = "<hindsight_memories>";
export const MEMORY_CLOSE = "</hindsight_memories>";

export const RECALL_PREAMBLE =
	"Relevant memories from past sessions (prioritize recent when conflicting). " +
	"Only use memories directly useful to continue this conversation; ignore the rest. " +
	"This block was injected by auto-recall; the user did not type it:";

/** A trimmed recall result — only the fields we format. */
export interface RecallResultLite {
	id: string;
	text: string;
	type?: string | null;
}

/** Loose shape for pi AgentMessage; we only read role + content defensively. */
export interface LooseMessage {
	role?: string;
	content?: unknown;
	customType?: string;
}

/** Lowercase, dash-collapse a tag value; drop anything unsafe. */
export function sanitizeTag(value: string): string {
	return value
		.toLowerCase()
		.replace(/[^a-z0-9._-]+/g, "-")
		.replace(/^-+|-+$/g, "")
		.slice(0, 64);
}

/**
 * Find the main repository directory for cwd. A linked worktree's `.git` file
 * points into `<main>/.git/worktrees/<name>`, so every worktree maps to its
 * main checkout. Null outside a git repository.
 */
export function findRepoRoot(cwd: string): string | null {
	let dir = path.resolve(cwd);
	try {
		dir = fs.realpathSync(dir); // a symlinked alias maps to the same repo
	} catch {
		/* missing path: walk the literal one */
	}
	for (;;) {
		const dotGit = path.join(dir, ".git");
		try {
			const stat = fs.statSync(dotGit);
			if (stat.isDirectory()) return dir;
			const m = /^gitdir:\s*(.+)$/m.exec(fs.readFileSync(dotGit, "utf8"));
			if (!m) return dir;
			const gitdir = path.resolve(dir, m[1].trim());
			const i = gitdir.lastIndexOf(`${path.sep}.git${path.sep}worktrees${path.sep}`);
			return i >= 0 ? gitdir.slice(0, i) : dir;
		} catch {
			/* no .git here; keep walking up */
		}
		const parent = path.dirname(dir);
		if (parent === dir) return null;
		dir = parent;
	}
}

/**
 * Derive a `project:<name>` tag: the main repository's directory name when cwd
 * is inside git (so worktrees and subdirectories share one tag), else the cwd
 * basename. Null if undecidable.
 */
export function deriveProjectTag(cwd: string | undefined): string | null {
	if (!cwd) return null;
	const root = findRepoRoot(cwd) ?? cwd;
	const base = sanitizeTag(path.basename(root.replace(/\/+$/, "")));
	return base ? `project:${base}` : null;
}

/** Characters of the previous assistant reply added to the recall query. */
export const RECALL_CONTEXT_CHARS = 300;

/**
 * Build the recall query. The prompt alone is often anaphoric ("this rule",
 * "continue"), so the start of the previous assistant reply is appended as
 * context. The prompt stays first so a topic switch still wins. When the
 * prompt was sent by an extension (e.g. a compaction "continue"), it is
 * boilerplate and only the context is used.
 */
export function buildRecallQuery(
	prompt: string | undefined,
	maxChars: number,
	opts: { previousReply?: string; includePrompt?: boolean } = {},
): string {
	const cleaned = stripMemoryBlocks(prompt ?? "").trim();
	const user = cleaned.length > maxChars ? cleaned.slice(0, maxChars) : cleaned;
	const reply = stripMemoryBlocks(opts.previousReply ?? "").trim().slice(0, RECALL_CONTEXT_CHARS);
	if (!reply) return user;
	const context = `Context (previous assistant reply): ${reply}`;
	if (opts.includePrompt === false || !user) return context;
	return `User: ${user}\n\n${context}`;
}

/** Text of the most recent assistant message with text on a session branch. */
export function lastAssistantText(entries: Array<{ type?: string; message?: LooseMessage }>): string {
	for (let i = entries.length - 1; i >= 0; i--) {
		const m = entries[i]?.type === "message" ? entries[i].message : undefined;
		if (m?.role !== "assistant") continue;
		const text = extractText(m, false).trim();
		if (text) return text;
	}
	return "";
}

/** Remove any <hindsight_memories>...</hindsight_memories> spans (feedback-loop guard). */
export function stripMemoryBlocks(text: string): string {
	if (!text || text.indexOf(MEMORY_OPEN) === -1) return text;
	const re = new RegExp(`${MEMORY_OPEN}[\\s\\S]*?${MEMORY_CLOSE}`, "g");
	return text.replace(re, "").replace(/\n{3,}/g, "\n\n").trim();
}

/** Format recalled results into an injectable block. Empty string if no usable results. */
export function formatMemoryBlock(results: RecallResultLite[], preamble = RECALL_PREAMBLE): string {
	const lines = results
		.map((r) => (r.text || "").trim())
		.filter((t) => t.length > 0)
		.map((t) => `- ${t}`);
	if (lines.length === 0) return "";
	return `${MEMORY_OPEN}\n${preamble}\n\n${lines.join("\n")}\n${MEMORY_CLOSE}`;
}

/** Extract plain text from a message's content (string or content-block array). */
export function extractText(message: LooseMessage, includeToolCalls: boolean): string {
	const c = message.content;
	if (typeof c === "string") return c;
	if (!Array.isArray(c)) return "";
	const parts: string[] = [];
	for (const block of c as Array<Record<string, unknown>>) {
		if (!block || typeof block !== "object") continue;
		const t = block.type;
		if ((t === "text" || t === undefined) && typeof block.text === "string") {
			parts.push(block.text);
		} else if (includeToolCalls && (t === "toolCall" || t === "toolUse" || t === "tool_use")) {
			const name = (block.name as string) || (block.toolName as string) || "tool";
			let args = "";
			try {
				args = JSON.stringify(block.arguments ?? block.input ?? block.args ?? {});
			} catch {
				args = "";
			}
			parts.push(`[tool: ${name} ${args}]`);
		}
	}
	return parts.join("\n");
}

/**
 * Serialize messages into a plain-text transcript for retain. Keeps only the
 * configured roles, strips injected memory blocks (so auto-recall output is
 * never re-ingested), and drops empty turns.
 */
export function messagesToTranscript(
	messages: LooseMessage[],
	opts: { roles: string[]; includeToolCalls: boolean },
): string {
	const roleSet = new Set(opts.roles);
	const out: string[] = [];
	for (const m of messages || []) {
		const role = m.role || "";
		// Never re-ingest our own injected recall block.
		if (m.customType === "hindsight_memories") continue;
		if (!roleSet.has(role)) continue;
		const text = stripMemoryBlocks(extractText(m, opts.includeToolCalls)).trim();
		if (!text) continue;
		const label = role === "user" ? "User" : role === "assistant" ? "Assistant" : role;
		out.push(`${label}: ${text}`);
	}
	return out.join("\n\n");
}
