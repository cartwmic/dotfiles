// Tests for the ntfy notify extension pure helpers.
// Run: node --test dot_pi/agent/extensions/ntfy/index.test.ts
//
// Covers acceptance criteria:
//   pi-ntfy-notify.notification-includes-content-excerpt
//   pi-ntfy-notify.notification-identifies-session
import assert from "node:assert/strict";
import { test } from "node:test";
import { buildNotification, extractExcerpt, lastAssistantText, loadConfig } from "./index.ts";

// --- pi-ntfy-notify.notification-includes-content-excerpt ---

test("extractExcerpt: collapses whitespace", () => {
	assert.equal(extractExcerpt("hello\n\n  world\t!", 200), "hello world !");
});

test("extractExcerpt: truncates with indicator when over max", () => {
	const out = extractExcerpt("abcdefghij", 5);
	assert.equal(out.length, 5);
	assert.ok(out.endsWith("…"));
	assert.equal(out, "abcd…");
});

test("extractExcerpt: no truncation when within max", () => {
	assert.equal(extractExcerpt("short", 200), "short");
});

test("extractExcerpt: placeholder when no text", () => {
	assert.equal(extractExcerpt("", 200), "(no text)");
	assert.equal(extractExcerpt("   \n\t ", 200), "(no text)");
});

test("lastAssistantText: returns text blocks, excludes thinking, picks last assistant", () => {
	const messages = [
		{ role: "user", content: [{ type: "text", text: "hi" }] },
		{
			role: "assistant",
			content: [
				{ type: "thinking", thinking: "secret reasoning" },
				{ type: "text", text: "first answer" },
			],
		},
		{ role: "toolResult", content: [{ type: "text", text: "tool output" }] },
		{
			role: "assistant",
			content: [
				{ type: "thinking", thinking: "more reasoning" },
				{ type: "text", text: "final answer" },
				{ type: "tool_call", id: "x" },
			],
		},
	];
	const text = lastAssistantText(messages);
	assert.equal(text, "final answer");
	assert.ok(!text.includes("reasoning"));
});

test("lastAssistantText: empty when no assistant message", () => {
	assert.equal(lastAssistantText([{ role: "user", content: [{ type: "text", text: "hi" }] }]), "");
});

// --- pi-ntfy-notify.notification-identifies-session ---

test("buildNotification: uses session name + zellij + cwd + excerpt", () => {
	const n = buildNotification({
		sessionName: "bug123",
		sessionId: "a3f9c2010000",
		zellij: "work",
		cwd: "/home/me/proj",
		excerpt: "what next?",
	});
	assert.equal(n.title, "pi ready: bug123");
	assert.equal(n.body, "zellij:work · /home/me/proj · what next?");
});

test("buildNotification: falls back to short session id when unnamed", () => {
	const n = buildNotification({
		sessionId: "a3f9c2010000",
		cwd: "/p",
		excerpt: "x",
	});
	assert.equal(n.title, "pi ready: a3f9c201");
});

test("buildNotification: omits zellij segment when env unset", () => {
	const n = buildNotification({
		sessionName: "s",
		sessionId: "id",
		zellij: undefined,
		cwd: "/p",
		excerpt: "x",
	});
	assert.equal(n.body, "/p · x");
});

// --- pi-ntfy-notify.no-op-when-unconfigured ---

test("loadConfig: disabled config when dir has no config.json", () => {
	const cfg = loadConfig("/nonexistent-dir-xyz");
	assert.equal(cfg.url, "");
	assert.equal(cfg.maxExcerptChars, 200);
});
