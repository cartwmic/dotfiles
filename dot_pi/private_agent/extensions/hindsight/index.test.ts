// Tests for the hindsight extension pure helpers.
// Run: node --test dot_pi/agent/extensions/hindsight/index.test.ts
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { test } from "node:test";
import { applyEnvOverrides, DEFAULTS, loadEnabled, parseConfig, saveEnabled } from "./config.ts";
import {
	buildRecallQuery,
	deriveProjectTag,
	extractText,
	formatMemoryBlock,
	MEMORY_CLOSE,
	MEMORY_OPEN,
	messagesToTranscript,
	sanitizeTag,
	stripMemoryBlocks,
} from "./content.ts";
import { parseToggle } from "./index.ts";

// --- config ---

test("parseConfig: empty -> DEFAULTS", () => {
	assert.deepEqual(parseConfig(undefined), DEFAULTS);
	assert.deepEqual(parseConfig("not json"), DEFAULTS);
});

test("parseConfig: overrides + trailing-slash trim + clamps", () => {
	const c = parseConfig(
		JSON.stringify({ apiUrl: "https://h.example.com/", retainEveryNTurns: 0, recallBudget: "bad" }),
	);
	assert.equal(c.apiUrl, "https://h.example.com");
	assert.equal(c.retainEveryNTurns, 1); // clamped to >= 1
	assert.equal(c.recallBudget, "mid"); // invalid -> default
});

test("applyEnvOverrides: url/token/flags", () => {
	const c = applyEnvOverrides(DEFAULTS, {
		HINDSIGHT_API_URL: "https://x.example.com/",
		HINDSIGHT_API_TOKEN: "tok",
		HINDSIGHT_AUTO_RETAIN: "false",
		HINDSIGHT_DEBUG: "true",
	} as NodeJS.ProcessEnv);
	assert.equal(c.apiUrl, "https://x.example.com");
	assert.equal(c.apiToken, "tok");
	assert.equal(c.autoRetain, false);
	assert.equal(c.debug, true);
});

test("loadEnabled/saveEnabled: sidecar override", () => {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "hs-"));
	assert.equal(loadEnabled(dir, true), true); // no state file -> default
	saveEnabled(dir, false);
	assert.equal(loadEnabled(dir, true), false); // override wins
	fs.rmSync(dir, { recursive: true, force: true });
});

// --- tags ---

test("sanitizeTag: lowercase, collapse, trim", () => {
	assert.equal(sanitizeTag("My Repo!!"), "my-repo");
	assert.equal(sanitizeTag("--a__b--"), "a__b");
});

test("deriveProjectTag: from cwd basename", () => {
	assert.equal(deriveProjectTag("/Users/x/code/Chezmoi/"), "project:chezmoi");
	assert.equal(deriveProjectTag(undefined), null);
});

// --- recall query + block ---

test("buildRecallQuery: strips prior blocks + truncates", () => {
	const q = buildRecallQuery(`hello ${MEMORY_OPEN}\nold\n${MEMORY_CLOSE} world`, 800);
	// block removal leaves the surrounding spaces; that's fine for a query
	assert.equal(q, "hello  world");
});

test("buildRecallQuery: truncation", () => {
	assert.equal(buildRecallQuery("abcdef", 3), "abc");
});

test("formatMemoryBlock: wraps non-empty, empty when no results", () => {
	assert.equal(formatMemoryBlock([]), "");
	assert.equal(formatMemoryBlock([{ id: "1", text: "   " }]), "");
	const b = formatMemoryBlock([
		{ id: "1", text: "Uses pnpm" },
		{ id: "2", text: "Prefers tabs" },
	]);
	assert.ok(b.startsWith(MEMORY_OPEN));
	assert.ok(b.endsWith(MEMORY_CLOSE));
	assert.ok(b.includes("- Uses pnpm"));
	assert.ok(b.includes("- Prefers tabs"));
});

// --- strip ---

test("stripMemoryBlocks: removes spans, collapses blank lines", () => {
	const t = `a\n${MEMORY_OPEN}\nx\n${MEMORY_CLOSE}\n\n\nb`;
	assert.equal(stripMemoryBlocks(t), "a\n\nb");
	assert.equal(stripMemoryBlocks("plain"), "plain");
});

// --- transcript ---

test("extractText: string + block array + tool calls", () => {
	assert.equal(extractText({ role: "user", content: "hi" }, false), "hi");
	assert.equal(
		extractText({ role: "assistant", content: [{ type: "text", text: "yo" }] }, false),
		"yo",
	);
	const withTool = extractText(
		{ role: "assistant", content: [{ type: "toolCall", name: "bash", arguments: { cmd: "ls" } }] },
		true,
	);
	assert.ok(withTool.includes("[tool: bash"));
	assert.equal(
		extractText({ role: "assistant", content: [{ type: "toolCall", name: "bash" }] }, false),
		"",
	);
});

test("messagesToTranscript: filters roles, drops injected blocks", () => {
	const msgs = [
		{ role: "user", content: "fix the bug" },
		{ role: "custom", customType: "hindsight_memories", content: "should be dropped" },
		{ role: "assistant", content: `done ${MEMORY_OPEN}\nx\n${MEMORY_CLOSE}` },
		{ role: "system", content: "ignored role" },
	];
	const t = messagesToTranscript(msgs, { roles: ["user", "assistant"], includeToolCalls: false });
	assert.equal(t, "User: fix the bug\n\nAssistant: done");
	assert.ok(!t.includes("hindsight_memories"));
	assert.ok(!t.includes("ignored role"));
});

// --- toggle ---

test("parseToggle", () => {
	assert.equal(parseToggle(""), "status");
	assert.equal(parseToggle("status"), "status");
	assert.equal(parseToggle("on"), "on");
	assert.equal(parseToggle("OFF"), "off");
	assert.equal(parseToggle("toggle"), "toggle");
	assert.equal(parseToggle("wat"), "invalid");
});
