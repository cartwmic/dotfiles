// Tests for the ntfy notify extension pure helpers.
// Run: node --test dot_pi/agent/extensions/ntfy/index.test.ts
//
// Covers acceptance criteria:
//   pi-ntfy-notify.notification-includes-content-excerpt
//   pi-ntfy-notify.notification-identifies-session
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { test } from "node:test";
import {
	buildNotification,
	extractExcerpt,
	lastAssistantText,
	loadConfig,
	loadEnabled,
	parseToggle,
	saveEnabled,
} from "./index.ts";

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
	assert.equal(cfg.enabled, true);
});

// --- toggle setting ---

test("loadConfig: enabled defaults true, honors explicit false", () => {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ntfy-cfg-"));
	try {
		fs.writeFileSync(path.join(dir, "config.json"), JSON.stringify({ url: "u" }));
		assert.equal(loadConfig(dir).enabled, true, "absent -> true");
		fs.writeFileSync(path.join(dir, "config.json"), JSON.stringify({ url: "u", enabled: false }));
		assert.equal(loadConfig(dir).enabled, false, "false -> false");
		fs.writeFileSync(path.join(dir, "config.json"), JSON.stringify({ url: "u", enabled: true }));
		assert.equal(loadConfig(dir).enabled, true, "true -> true");
	} finally {
		fs.rmSync(dir, { recursive: true, force: true });
	}
});

test("parseToggle: maps args to actions", () => {
	assert.equal(parseToggle(""), "status");
	assert.equal(parseToggle("status"), "status");
	assert.equal(parseToggle("on"), "on");
	assert.equal(parseToggle(" ON "), "on");
	assert.equal(parseToggle("enable"), "on");
	assert.equal(parseToggle("off"), "off");
	assert.equal(parseToggle("disable"), "off");
	assert.equal(parseToggle("toggle"), "toggle");
	assert.equal(parseToggle("nonsense"), "invalid");
});

test("loadEnabled: state.json override wins over config default", () => {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ntfy-state-"));
	try {
		assert.equal(loadEnabled(dir, true), true, "no override -> config default");
		assert.equal(loadEnabled(dir, false), false, "no override -> config default");
		saveEnabled(dir, false);
		assert.equal(loadEnabled(dir, true), false, "override false beats config true");
		saveEnabled(dir, true);
		assert.equal(loadEnabled(dir, false), true, "override true beats config false");
	} finally {
		fs.rmSync(dir, { recursive: true, force: true });
	}
});
