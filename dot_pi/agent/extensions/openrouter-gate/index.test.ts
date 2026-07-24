// Tests for the openrouter-gate pure helpers.
// Run: node --test dot_pi/agent/extensions/openrouter-gate/index.test.ts
import assert from "node:assert/strict";
import { test } from "node:test";
import { parseSubcommand, readStash } from "./index.ts";

const AUTH_PATH = "/fake/auth.json";

function reader(obj: unknown): { readFile: (p: string) => string; authPath: string } {
	return {
		readFile: (p) => {
			assert.equal(p, AUTH_PATH);
			return JSON.stringify(obj);
		},
		authPath: AUTH_PATH,
	};
}

test("readStash: stash present with key", () => {
	const s = readStash(reader({ "openrouter-stashed": { type: "api_key", key: "sk-or-v1-abc" } }));
	assert.equal(s.key, "sk-or-v1-abc");
	assert.equal(s.stashPresent, true);
	assert.equal(s.liveEntryPresent, false);
	assert.equal(s.error, undefined);
});

test("readStash: stash present but malformed (no key)", () => {
	const s = readStash(reader({ "openrouter-stashed": { type: "api_key" } }));
	assert.equal(s.key, undefined);
	assert.equal(s.stashPresent, true);
});

test("readStash: empty-string key is unusable", () => {
	const s = readStash(reader({ "openrouter-stashed": { key: "" } }));
	assert.equal(s.key, undefined);
	assert.equal(s.stashPresent, true);
});

test("readStash: live openrouter entry detected (gate bypassed)", () => {
	const s = readStash(reader({ openrouter: { type: "api_key", key: "sk-or-v1-live" } }));
	assert.equal(s.liveEntryPresent, true);
	assert.equal(s.stashPresent, false);
	assert.equal(s.key, undefined);
});

test("readStash: both live and stash present", () => {
	const s = readStash(
		reader({
			openrouter: { type: "api_key", key: "live" },
			"openrouter-stashed": { type: "api_key", key: "stashed" },
		}),
	);
	assert.equal(s.liveEntryPresent, true);
	assert.equal(s.stashPresent, true);
	assert.equal(s.key, "stashed");
});

test("readStash: missing file reports error, never throws", () => {
	const s = readStash({
		readFile: () => {
			throw new Error("ENOENT");
		},
		authPath: AUTH_PATH,
	});
	assert.equal(s.stashPresent, false);
	assert.equal(s.liveEntryPresent, false);
	assert.match(s.error ?? "", /ENOENT/);
});

test("readStash: malformed json reports error, never throws", () => {
	const s = readStash({ readFile: () => "{not json", authPath: AUTH_PATH });
	assert.equal(s.stashPresent, false);
	assert.ok(s.error);
});

test("parseSubcommand: canonical values", () => {
	assert.equal(parseSubcommand("on"), "on");
	assert.equal(parseSubcommand(" OFF "), "off");
	assert.equal(parseSubcommand("status"), "status");
	assert.equal(parseSubcommand(""), "status");
	assert.equal(parseSubcommand("bogus"), "help");
});
