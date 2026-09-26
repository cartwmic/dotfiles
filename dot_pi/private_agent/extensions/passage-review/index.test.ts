import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync, chmodSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import extension from "./index.ts";

function fakeContext(overrides: Record<string, unknown> = {}) {
	const notices: Array<{ message: string; type?: string }> = [];
	const order: string[] = [];
	const branch = [
		{ type: "message", message: { role: "user", content: "question" } },
		{ type: "message", message: { role: "assistant", content: [{ type: "text", text: "older reply" }] } },
		{ type: "message", message: { role: "assistant", content: [{ type: "toolCall", id: "call-1" }] } },
		{ type: "message", message: { role: "assistant", content: [{ type: "text", text: "latest assistant reply" }] } },
	] as any;
	const ctx = {
		mode: "tui",
		hasUI: true,
		cwd: process.cwd(),
		isIdle: () => true,
		sessionManager: {
			getBranch: () => branch,
			getSessionId: () => "test-session",
		},
		ui: {
			notify: (message: string, type?: string) => notices.push({ message, type }),
			custom: async (factory: any) => {
				await factory(
					{ stop: () => order.push("pause"), start: () => order.push("resume") },
					{},
					{},
					() => order.push("done"),
				);
			},
		},
		...overrides,
	} as any;
	return { ctx, notices, order };
}

test("/review pipes only the latest reply into the standalone source-entry command", async () => {
	const directory = mkdtempSync(join(tmpdir(), "passage-review-extension-"));
	const fakeCommand = join(directory, "passage-review");
	const argsPath = join(directory, "args.txt");
	const sourcePath = join(directory, "source.txt");
	writeFileSync(
		fakeCommand,
		"#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$PASSAGE_REVIEW_TEST_ARGS\"\ncat > \"$PASSAGE_REVIEW_TEST_SOURCE\"\n",
	);
	chmodSync(fakeCommand, 0o700);
	const previous = {
		bin: process.env.PASSAGE_REVIEW_BIN,
		args: process.env.PASSAGE_REVIEW_TEST_ARGS,
		source: process.env.PASSAGE_REVIEW_TEST_SOURCE,
	};
	process.env.PASSAGE_REVIEW_BIN = fakeCommand;
	process.env.PASSAGE_REVIEW_TEST_ARGS = argsPath;
	process.env.PASSAGE_REVIEW_TEST_SOURCE = sourcePath;
	try {
		let command: any;
		extension({ registerCommand: (_name: string, value: unknown) => (command = value) } as any);
		assert.ok(command);
		const { ctx, order, notices } = fakeContext();
		await command.handler("ignored args", ctx);
		assert.deepEqual(readFileSync(argsPath, "utf8").trimEnd().split("\n"), [
			"new",
			"--title",
			"Pi reply — session test-session",
		]);
		assert.equal(readFileSync(sourcePath, "utf8"), "latest assistant reply");
		assert.deepEqual(order, ["pause", "resume", "done"]);
		assert.deepEqual(notices.map((notice) => notice.type), ["info"]);
		assert.ok(!readFileSync(argsPath, "utf8").includes("export"));
		assert.ok(!readFileSync(argsPath, "utf8").includes("archive"));
	} finally {
		if (previous.bin === undefined) delete process.env.PASSAGE_REVIEW_BIN;
		else process.env.PASSAGE_REVIEW_BIN = previous.bin;
		if (previous.args === undefined) delete process.env.PASSAGE_REVIEW_TEST_ARGS;
		else process.env.PASSAGE_REVIEW_TEST_ARGS = previous.args;
		if (previous.source === undefined) delete process.env.PASSAGE_REVIEW_TEST_SOURCE;
		else process.env.PASSAGE_REVIEW_TEST_SOURCE = previous.source;
		rmSync(directory, { recursive: true, force: true });
	}
});

test("command registers under /review and does not spawn for an unavailable TUI", async () => {
	let command: any;
	extension({ registerCommand: (_name: string, value: unknown) => (command = value) } as any);
	assert.ok(command);
	const { ctx, notices } = fakeContext({ mode: "rpc", hasUI: true });
	await command.handler("", ctx);
	assert.deepEqual(notices.map((notice) => notice.message), [
		"/review needs Pi's interactive terminal; use passage-review directly otherwise.",
	]);
});
