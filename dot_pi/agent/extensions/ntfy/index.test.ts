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
	buildJumpClickUrl,
	buildNotification,
	extractExcerpt,
	extractQuestionExcerpt,
	lastAssistantText,
	loadConfig,
	loadEnabled,
	parseToggle,
	parseZellijTabName,
	saveEnabled,
} from "./index.ts";

// --- jump Click deep-link (tap-to-jump) ---

test("buildJumpClickUrl: terminal_N pane id rides the URL path", () => {
	assert.equal(buildJumpClickUrl("terminal_25"), "termux://zellij-jump/terminal_25");
});

test("buildJumpClickUrl: bare integer pane id accepted", () => {
	assert.equal(buildJumpClickUrl("25"), "termux://zellij-jump/25");
});

test("buildJumpClickUrl: honors custom base and strips trailing slash", () => {
	assert.equal(buildJumpClickUrl("terminal_7", "termux://zellij-jump/"), "termux://zellij-jump/terminal_7");
});

test("buildJumpClickUrl: undefined for absent / non-terminal / malformed pane id", () => {
	assert.equal(buildJumpClickUrl(undefined), undefined, "absent");
	assert.equal(buildJumpClickUrl(""), undefined, "empty");
	assert.equal(buildJumpClickUrl("plugin_3"), undefined, "plugin pane not jumpable");
	assert.equal(buildJumpClickUrl("terminal_"), undefined, "empty tail");
	assert.equal(buildJumpClickUrl("garbage"), undefined, "non-numeric");
});

test("loadConfig: jumpDeepLinkBase defaults, honors explicit override", () => {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ntfy-jump-"));
	try {
		fs.writeFileSync(path.join(dir, "config.json"), JSON.stringify({ url: "http://x/t" }));
		assert.equal(loadConfig(dir).jumpDeepLinkBase, "termux://zellij-jump", "absent -> default");
		fs.writeFileSync(
			path.join(dir, "config.json"),
			JSON.stringify({ url: "http://x/t", jumpDeepLinkBase: "myscheme://jump" }),
		);
		assert.equal(loadConfig(dir).jumpDeepLinkBase, "myscheme://jump", "explicit override");
	} finally {
		fs.rmSync(dir, { recursive: true, force: true });
	}
});

// --- ask_user_question excerpt ---

test("extractQuestionExcerpt: uses first question text", () => {
	const out = extractQuestionExcerpt({ questions: [{ question: "Which approach?" }] }, 200);
	assert.equal(out, "❓ Which approach?");
});

test("extractQuestionExcerpt: prefixes count when batched", () => {
	const out = extractQuestionExcerpt(
		{ questions: [{ question: "A?" }, { question: "B?" }, { question: "C?" }] },
		200,
	);
	assert.equal(out, "❓ [3 questions] A?");
});

test("extractQuestionExcerpt: placeholder when no questions", () => {
	assert.equal(extractQuestionExcerpt({ questions: [] }, 200), "❓ (waiting for your answer)");
	assert.equal(extractQuestionExcerpt(undefined, 200), "❓ (waiting for your answer)");
	assert.equal(extractQuestionExcerpt({}, 200), "❓ (waiting for your answer)");
});

test("extractQuestionExcerpt: truncates long question", () => {
	const out = extractQuestionExcerpt({ questions: [{ question: "x".repeat(50) }] }, 10);
	assert.ok(out.endsWith("…"));
	assert.ok(out.length <= 10);
});

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

test("buildNotification: title = zellij session + tab + pi name; body = excerpt", () => {
	const n = buildNotification({
		sessionName: "bug123",
		sessionId: "a3f9c2010000",
		zellijSession: "workspace",
		tabName: "chezmoi",
		excerpt: "what next?",
	});
	assert.equal(n.title, "workspace / chezmoi / bug123");
	assert.equal(n.body, "what next?");
});

test("buildNotification: falls back to short session id when unnamed", () => {
	const n = buildNotification({
		sessionId: "a3f9c2010000",
		zellijSession: "workspace",
		tabName: "chezmoi",
		excerpt: "x",
	});
	assert.equal(n.title, "workspace / chezmoi / a3f9c201");
});

test("buildNotification: omits zellij/tab segments when unavailable (pi name only)", () => {
	const n = buildNotification({
		sessionName: "solo",
		sessionId: "id",
		excerpt: "x",
	});
	assert.equal(n.title, "solo");
	assert.equal(n.body, "x");
});

test("parseZellijTabName: finds tab whose pane matches cwd (leading slash stripped)", () => {
	const layout = [
		'    tab name="chezmoi" focus=true {',
		'        pane command="pi" cwd="Users/me/.local/share/chezmoi" focus=true {',
		"        }",
		"    }",
		'    tab name="homelab" {',
		'        pane command="pi" cwd="Volumes/Workshop/git/homelab" {',
		"        }",
		"    }",
	].join("\n");
	assert.equal(parseZellijTabName(layout, "/Users/me/.local/share/chezmoi"), "chezmoi");
	assert.equal(parseZellijTabName(layout, "/Volumes/Workshop/git/homelab"), "homelab");
	assert.equal(parseZellijTabName(layout, "/nowhere"), undefined);
});

// --- pi-ntfy-notify.no-op-when-unconfigured ---

test("loadConfig: disabled config when dir has no config.json", () => {
	const cfg = loadConfig("/nonexistent-dir-xyz");
	assert.equal(cfg.url, "");
	assert.equal(cfg.maxExcerptChars, 200);
	assert.equal(cfg.enabled, true);
});

// --- toggle setting ---
// Covers acceptance criterion: pi-ntfy-notify.notifications-can-be-toggled

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

// ── Send-failure visibility (make-ntfy-send-failures-visible) ────────────────
// Covers acceptance criteria:
//   pi-ntfy-notify.delivery-failures-are-non-fatal (non-2xx is a failure)
//   pi-ntfy-notify.send-failures-are-warned-in-the-ui
//   pi-ntfy-notify.status-reports-send-outcomes
//   pi-ntfy-notify.capped-send-log
import {
	appendSendLog,
	buildLogLine,
	describeSendError,
	formatSendStatus,
	newSendState,
	reactToSendOutcome,
	recordOutcome,
	sendNotification,
} from "./index.ts";

test("sendNotification resolves on 2xx and rejects on non-2xx (non-2xx is a failure)", async () => {
	const realFetch = globalThis.fetch;
	try {
		globalThis.fetch = (async () => ({ ok: true, status: 200 })) as unknown as typeof fetch;
		await sendNotification("https://example.invalid/topic", "t", "b");

		globalThis.fetch = (async () => ({ ok: false, status: 500 })) as unknown as typeof fetch;
		await assert.rejects(
			() => sendNotification("https://example.invalid/topic", "t", "b"),
			/HTTP 500/,
			"non-2xx must reject with the HTTP status",
		);
	} finally {
		globalThis.fetch = realFetch;
	}
});

test("recordOutcome + formatSendStatus report counts and last outcomes", () => {
	const state = newSendState();
	assert.equal(formatSendStatus(state), "no sends this session");
	const t1 = new Date("2026-07-10T22:00:00Z");
	const t2 = new Date("2026-07-10T22:05:00Z");
	recordOutcome(state, true, undefined, t1);
	recordOutcome(state, false, "HTTP 500", t2);
	const s = formatSendStatus(state);
	assert.match(s, /sends: 1 ok \/ 1 failed/);
	assert.match(s, /last ok 2026-07-10T22:00:00/);
	assert.match(s, /last fail 2026-07-10T22:05:00.*HTTP 500/);
});

test("describeSendError is bounded and whitespace-collapsed", () => {
	assert.equal(describeSendError(new Error("HTTP 503")), "Error: HTTP 503");
	const long = describeSendError(new Error(`x${" y".repeat(500)}`));
	assert.ok(long.length <= 200, "reason is hard-bounded");
	assert.ok(!long.includes("\n"), "no newlines in reason");
	assert.equal(describeSendError(""), "unknown error");
});

test("buildLogLine records timestamp + outcome metadata only", () => {
	const at = new Date("2026-07-10T22:00:00Z");
	assert.equal(buildLogLine(true, undefined, at), "2026-07-10T22:00:00.000Z ok");
	assert.equal(buildLogLine(false, "HTTP 500", at), "2026-07-10T22:00:00.000Z fail HTTP 500");
});

test("appendSendLog appends and rotates past the cap", () => {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ntfy-log-"));
	try {
		appendSendLog(dir, "line-1", 64);
		appendSendLog(dir, "line-2", 64);
		const log = path.join(dir, "send.log");
		assert.equal(fs.readFileSync(log, "utf8"), "line-1\nline-2\n");

		// Exceed the cap: next append rotates first, then writes fresh.
		appendSendLog(dir, "x".repeat(80), 64);
		appendSendLog(dir, "after-rotate", 64);
		assert.ok(fs.existsSync(path.join(dir, "send.log.old")), "rotated file exists");
		assert.equal(fs.readFileSync(log, "utf8"), "after-rotate\n", "fresh log after rotation");
	} finally {
		fs.rmSync(dir, { recursive: true, force: true });
	}
});

test("reactToSendOutcome: failure warns with reason, records state, appends log", async () => {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ntfy-react-"));
	try {
		const state = newSendState();
		const warnings: string[] = [];
		reactToSendOutcome(Promise.reject(new Error("HTTP 500")), state, dir, (m) => warnings.push(m));
		await new Promise((r) => setTimeout(r, 10));
		assert.deepEqual(warnings, ["ntfy send failed: Error: HTTP 500"]);
		assert.equal(state.failCount, 1);
		assert.match(fs.readFileSync(path.join(dir, "send.log"), "utf8"), /fail Error: HTTP 500/);
	} finally {
		fs.rmSync(dir, { recursive: true, force: true });
	}
});

test("reactToSendOutcome: success is silent in the UI but recorded", async () => {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ntfy-react-ok-"));
	try {
		const state = newSendState();
		const warnings: string[] = [];
		reactToSendOutcome(Promise.resolve(), state, dir, (m) => warnings.push(m));
		await new Promise((r) => setTimeout(r, 10));
		assert.deepEqual(warnings, [], "no warning on success");
		assert.equal(state.okCount, 1);
		assert.match(fs.readFileSync(path.join(dir, "send.log"), "utf8"), /ok\n$/);
	} finally {
		fs.rmSync(dir, { recursive: true, force: true });
	}
});

test("reactToSendOutcome: a throwing warn surface never propagates", async () => {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ntfy-react-warnthrow-"));
	try {
		const state = newSendState();
		reactToSendOutcome(Promise.reject(new Error("HTTP 503")), state, dir, () => {
			throw new Error("UI gone");
		});
		await new Promise((r) => setTimeout(r, 10));
		assert.equal(state.failCount, 1, "state recorded despite warn throw");
	} finally {
		fs.rmSync(dir, { recursive: true, force: true });
	}
});
