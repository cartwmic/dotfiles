// Run: node --test dot_pi/private_agent/extensions/bash-default-timeout/index.test.ts
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import extension, { FALLBACK_TIMEOUT_SECONDS, loadDefaultTimeoutSeconds, timeoutHint } from "./index.ts";

const configWith = (text: string): string => {
	const path = join(mkdtempSync(join(tmpdir(), "bdt-")), "config.json");
	writeFileSync(path, text);
	return path;
};

test("reads defaultTimeoutSeconds, and falls back on a missing file or a bad value", () => {
	assert.equal(loadDefaultTimeoutSeconds(configWith('{"defaultTimeoutSeconds": 90}')), 90);
	assert.equal(loadDefaultTimeoutSeconds(join(tmpdir(), "bdt-does-not-exist.json")), FALLBACK_TIMEOUT_SECONDS);
	for (const bad of ["not json", "{}", '{"defaultTimeoutSeconds": 0}', '{"defaultTimeoutSeconds": -5}', '{"defaultTimeoutSeconds": "60"}', '{"defaultTimeoutSeconds": 3000000}']) {
		assert.equal(loadDefaultTimeoutSeconds(configWith(bad)), FALLBACK_TIMEOUT_SECONDS, bad);
	}
});

type Handler = (event: any) => any;
const load = () => {
	const handlers: Record<string, Handler> = {};
	extension({ on: (name: string, handler: Handler) => (handlers[name] = handler) } as any);
	return handlers;
};

test("a bash call with no timeout gets the default; one with its own timeout is left alone; other tools are untouched", () => {
	const { tool_call } = load();
	const bare = { toolName: "bash", toolCallId: "a", input: { command: "ls" } };
	tool_call!(bare);
	assert.equal(bare.input.timeout, FALLBACK_TIMEOUT_SECONDS);
	const own = { toolName: "bash", toolCallId: "b", input: { command: "ls", timeout: 3600 } };
	tool_call!(own);
	assert.equal(own.input.timeout, 3600);
	const other = { toolName: "read", toolCallId: "c", input: { path: "x" } };
	tool_call!(other);
	assert.equal("timeout" in other.input, false);
});

test("the hint is added only when the default limit stopped the command", () => {
	const { tool_call, tool_result } = load();
	const expired = (id: string) => ({ toolCallId: id, isError: true, content: [{ type: "text", text: `Command timed out after ${FALLBACK_TIMEOUT_SECONDS} seconds` }] });
	tool_call!({ toolName: "bash", toolCallId: "d", input: {} });
	const result = tool_result!(expired("d"));
	assert.equal(result.content.at(-1).text, timeoutHint(FALLBACK_TIMEOUT_SECONDS));
	assert.equal(result.content.length, 2);
	// The model set its own timeout: no hint.
	tool_call!({ toolName: "bash", toolCallId: "e", input: { timeout: 5 } });
	assert.equal(tool_result!(expired("e")), undefined);
	// Defaulted, but the command failed some other way: no hint.
	tool_call!({ toolName: "bash", toolCallId: "f", input: {} });
	assert.equal(tool_result!({ toolCallId: "f", isError: true, content: [{ type: "text", text: "exit code 1" }] }), undefined);
	// Defaulted and succeeded.
	tool_call!({ toolName: "bash", toolCallId: "g", input: {} });
	assert.equal(tool_result!({ toolCallId: "g", isError: false, content: [{ type: "text", text: "ok" }] }), undefined);
});
