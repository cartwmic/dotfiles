import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { copyFileSync, chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync, appendFileSync } from "node:fs";
import http from "node:http";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import extension from "./index.ts";

const extensionDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(extensionDir, "../../../..");
const fakeBackend = path.join(repoRoot, "tests", "herdr-overview", "fake_recap_backend.py");
const SUCCESS_SUMMARY = "Recent work is complete. Present state: ready for the next step.";
const WAIT_MS = 10_000;

function delay(ms: number): Promise<void> {
	return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitFor(predicate: () => boolean, message: string, timeoutMs = WAIT_MS): Promise<void> {
	const deadline = Date.now() + timeoutMs;
	while (!predicate()) {
		if (Date.now() >= deadline) throw new Error(`Timed out waiting for ${message}`);
		await delay(20);
	}
}

function readJson(filePath: string): any {
	return JSON.parse(readFileSync(filePath, "utf8"));
}

function readRecord(dataRoot: string, recordId: string): any {
	for (const day of readdirSync(path.join(dataRoot, "records"))) {
		const filePath = path.join(dataRoot, "records", day, `${recordId}.json`);
		if (existsSync(filePath)) return readJson(filePath);
	}
	return undefined;
}

function sourceEntry(dataRoot: string, sourceId: string): any {
	const latest = readJson(path.join(dataRoot, "latest.json"));
	return latest.sources.find((item: any) => item.source_kind === "pi-session" && item.source_id === sourceId);
}

function promptFile(dataRoot: string, sessionId: string): string {
	const encoded = encodeURIComponent(sessionId).replace(/[!'()*]/g, (char) => `%${char.charCodeAt(0).toString(16).toUpperCase()}`);
	return path.join(dataRoot, "prompts", `${encoded}.json`);
}

interface TestWorld {
	root: string;
	dataRoot: string;
	tracePath: string;
	capturePath: string;
	piAgentDir: string;
	piSessionDir: string;
	env: Record<string, string>;
	setBackendMode(mode: "success" | "blank" | "nonzero"): void;
	close(): Promise<void>;
}

async function createWorld(): Promise<TestWorld> {
	const root = mkdtempSync(path.join(os.tmpdir(), "h5-"));
	const home = path.join(root, "home");
	const configHome = path.join(root, "config");
	const dataHome = path.join(root, "data");
	const configDir = path.join(configHome, "session-recap");
	const dataRoot = path.join(dataHome, "session-recap");
	const cliDir = path.join(root, "t1", "bin");
	const implementationDir = path.join(root, "t1", "share", "session-recap");
	const piAgentDir = path.join(root, "pi-agent");
	const piSessionDir = path.join(root, "pi-sessions");
	for (const dir of [home, configDir, dataRoot, cliDir, implementationDir, piAgentDir, piSessionDir]) {
		mkdirSync(dir, { recursive: true });
	}

	const cliPath = path.join(cliDir, "session-recap");
	copyFileSync(path.join(repoRoot, "dot_local", "bin", "executable_session-recap"), cliPath);
	chmodSync(cliPath, 0o755);
	copyFileSync(
		path.join(repoRoot, "dot_local", "share", "session-recap", "session_recap.py"),
		path.join(implementationDir, "session_recap.py"),
	);
	writeFileSync(
		path.join(configDir, "single-prompt.md"),
		readFileSync(path.join(repoRoot, "dot_config", "session-recap", "single-prompt.md.tmpl"), "utf8"),
	);
	writeFileSync(
		path.join(configDir, "group-prompt.md"),
		readFileSync(path.join(repoRoot, "dot_config", "session-recap", "group-prompt.md.tmpl"), "utf8"),
	);
	writeFileSync(path.join(piAgentDir, "settings.json"), JSON.stringify({ cacheWarming: "off", enableInstallTelemetry: false }));

	const tracePath = path.join(root, "trace.log");
	const capturePath = path.join(root, "backend-prompt.txt");
	const spyCliPath = path.join(root, "session-recap-spy");
	writeFileSync(
		spyCliPath,
		"#!/bin/sh\nprintf 'cli %s\\n' \"$*\" >> \"$HERDR_OVERVIEW_TEST_TRACE\"\nexec \"$SESSION_RECAP_REAL_BIN\" \"$@\"\n",
	);
	chmodSync(spyCliPath, 0o755);

	const configPath = path.join(configDir, "config.toml");
	const setBackendMode = (mode: "success" | "blank" | "nonzero") => {
		const command = [process.env.PYTHON ?? "python3", fakeBackend, mode];
		writeFileSync(configPath, `command = ${JSON.stringify(command)}\n`);
	};
	setBackendMode("success");

	const socketPath = path.join(root, "herdr.sock");
	let currentSnapshot: any = {
		protocol: 22,
		focused_pane_id: "ui-focused-pane",
		panes: [
			{ pane_id: "exact-pane", workspace_id: "workspace-exact", focused: false },
			{ pane_id: "ui-focused-pane", workspace_id: "workspace-wrong", focused: true },
		],
	};
	const calls: any[] = [];
	const herdrServer = net.createServer((socket) => {
		let buffer = "";
		socket.on("data", (chunk) => {
			buffer += chunk.toString("utf8");
			let newline = buffer.indexOf("\n");
			while (newline >= 0) {
				const line = buffer.slice(0, newline);
				buffer = buffer.slice(newline + 1);
				newline = buffer.indexOf("\n");
				if (!line.trim()) continue;
				const request = JSON.parse(line);
				appendFileSync(tracePath, `herdr ${request.method}\n`);
				const call: any = { method: request.method, params: request.params };
				if (request.method === "session.snapshot") {
					call.snapshot = currentSnapshot;
				} else if (request.method === "plugin.action.invoke") {
					try {
						const latest = readJson(path.join(dataRoot, "latest.json"));
						const piLatest = latest.sources.find((item: any) => item.source_kind === "pi-session");
						call.publishedRecord = piLatest ? readRecord(dataRoot, piLatest.latest_success_id) : undefined;
					} catch {
						call.publishedRecord = undefined;
					}
				}
				calls.push(call);
				const result = request.method === "session.snapshot" ? { snapshot: currentSnapshot } : {};
				socket.write(`${JSON.stringify({ id: request.id, result })}\n`);
				return;
			}
		});
	});
	await new Promise<void>((resolve, reject) => {
		herdrServer.once("error", reject);
		herdrServer.listen(socketPath, resolve);
	});

	return {
		root,
		dataRoot,
		tracePath,
		capturePath,
		piAgentDir,
		piSessionDir,
		env: {
			HOME: home,
			XDG_CONFIG_HOME: configHome,
			XDG_DATA_HOME: dataHome,
			SESSION_RECAP_BIN: spyCliPath,
			SESSION_RECAP_REAL_BIN: cliPath,
			HERDR_OVERVIEW_TEST_TRACE: tracePath,
			FAKE_RECAP_CAPTURE: capturePath,
			HERDR_SOCKET_PATH: socketPath,
			HERDR_PANE_ID: "exact-pane",
		},
		setBackendMode,
		close: async () => {
			await new Promise<void>((resolve) => herdrServer.close(() => resolve()));
			rmSync(root, { recursive: true, force: true });
		},
		// Tests update this snapshot through the server reference attached below.
		get snapshot() { return currentSnapshot; },
		set snapshot(value: unknown) { currentSnapshot = value; },
		calls,
	} as TestWorld & { snapshot: any; calls: any[] };
}

const ENV_KEYS = [
	"HOME",
	"XDG_CONFIG_HOME",
	"XDG_DATA_HOME",
	"SESSION_RECAP_BIN",
	"SESSION_RECAP_REAL_BIN",
	"HERDR_OVERVIEW_TEST_TRACE",
	"FAKE_RECAP_CAPTURE",
	"HERDR_SOCKET_PATH",
	"HERDR_PANE_ID",
] as const;

async function withProcessEnv<T>(values: Record<string, string>, callback: () => Promise<T>): Promise<T> {
	const old = new Map<string, string | undefined>(ENV_KEYS.map((key) => [key, process.env[key]]));
	for (const [key, value] of Object.entries(values)) process.env[key] = value;
	try {
		return await callback();
	} finally {
		for (const [key, value] of old) {
			if (value === undefined) delete process.env[key];
			else process.env[key] = value;
		}
	}
}

function readTrace(tracePath: string): string[] {
	if (!existsSync(tracePath)) return [];
	const text = readFileSync(tracePath, "utf8").trim();
	return text ? text.split("\n") : [];
}

function registeredHandlers(): Map<string, (...args: any[]) => any> {
	const handlers = new Map<string, (...args: any[]) => any>();
	extension({ on: (event: string, handler: (...args: any[]) => any) => handlers.set(event, handler) } as any);
	return handlers;
}

function fakeContext(sessionId: string, mode: "tui" | "rpc", idle: boolean, entries: unknown[]) {
	let stale = false;
	const target = {
		mode,
		isIdle: () => idle,
		sessionManager: {
			getSessionId: () => sessionId,
			getBranch: () => entries,
		},
	};
	return {
		ctx: new Proxy(target, {
			get(object, key, receiver) {
				if (stale) throw new Error("stale ExtensionContext used");
				return Reflect.get(object, key, receiver);
			},
		}),
		invalidate: () => { stale = true; },
	};
}

function responseEntry(text: string, stopReason = "stop") {
	return [{ type: "message", message: { role: "assistant", stopReason, content: [{ type: "text", text }] } }];
}

function latestPublished(dataRoot: string, sessionId: string): any {
	const entry = sourceEntry(dataRoot, sessionId);
	return entry ? readRecord(dataRoot, entry.latest_success_id) : undefined;
}

function promptRecord(dataRoot: string, sessionId: string): any {
	return readJson(promptFile(dataRoot, sessionId));
}

test("interactive prompt stays separate; settled publication uses exact pane membership once", async () => {
	const world = await createWorld();
	try {
		await withProcessEnv(world.env, async () => {
			const handlers = registeredHandlers();
			const oldContext = fakeContext("interactive-session", "tui", false, []);
			const realInput = handlers.get("input")!;
			await realInput({ type: "input", source: "interactive", text: "Fix the interactive request." }, oldContext.ctx);
			// Simulate replacement/reload by invalidating this callback's context before the next event.
			oldContext.invalidate();

			const continuation = realInput(
				{ type: "input", source: "extension", text: "generated continuation must not replace the prompt" },
				fakeContext("interactive-session", "tui", false, []).ctx,
			);
			assert.deepEqual(continuation, { action: "continue" });
			assert.equal(promptRecord(world.dataRoot, "interactive-session").text, "Fix the interactive request.");
			assert.equal(readTrace(world.tracePath).filter((line) => line.startsWith("cli prompt set ")).length, 1);

			const beforeIdle = handlers.get("agent_settled")!(
				{},
				fakeContext("interactive-session", "tui", false, responseEntry("Settled assistant answer.")).ctx,
			);
			assert.equal(beforeIdle, undefined);
			assert.deepEqual(readTrace(world.tracePath).map((line) => line.split(" ").slice(0, 2).join(" ")), ["cli prompt"]);

			await handlers.get("agent_settled")!(
				{},
				fakeContext("interactive-session", "tui", true, responseEntry("Settled assistant answer.")).ctx,
			);
			await waitFor(
				() => world.calls.some((call) => call.method === "plugin.action.invoke"),
				"the overview reconcile action",
			);

			const prompt = promptRecord(world.dataRoot, "interactive-session");
			const recap = latestPublished(world.dataRoot, "interactive-session");
			assert.equal(prompt.text, "Fix the interactive request.");
			assert.equal(prompt.working, false);
			assert.equal(prompt.pane_id, "exact-pane");
			assert.equal(recap.status, "published");
			assert.equal(recap.summary, SUCCESS_SUMMARY);
			assert.equal(recap.source_kind, "pi-session");
			assert.equal(recap.pane_id, "exact-pane");
			assert.equal(recap.workspace_id, "workspace-exact");
			assert.notEqual(prompt.text, recap.summary);
			assert.match(readFileSync(world.capturePath, "utf8"), /Settled assistant answer\./);
			assert.equal(world.calls.find((call) => call.method === "plugin.action.invoke").params.action_id, "overview.reconcile");
			assert.equal(world.calls.find((call) => call.method === "plugin.action.invoke").publishedRecord.record_id, recap.record_id);

			const order = readTrace(world.tracePath);
			const preparedAt = order.findIndex((line) => line.startsWith("cli prepare "));
			assert.ok(preparedAt >= 0);
			assert.equal(order[preparedAt + 1], "herdr session.snapshot");
			assert.match(order[preparedAt + 2], /^cli publish /);
			assert.equal(order[preparedAt + 3], "herdr plugin.action.invoke");

			await handlers.get("agent_settled")!(
				{},
				fakeContext("interactive-session", "tui", true, responseEntry("Settled assistant answer.")).ctx,
			);
			assert.equal(readTrace(world.tracePath).filter((line) => line.startsWith("cli prepare ")).length, 1);
			assert.equal(world.calls.filter((call) => call.method === "plugin.action.invoke").length, 1);
		});
	} finally {
		await world.close();
	}
});

interface RpcHarness {
	child: ReturnType<typeof spawn>;
	records: any[];
	stderr: () => string;
	sendPrompt(text: string): Promise<void>;
	waitForEvent(type: string, count: number): Promise<void>;
	close(): Promise<void>;
}

function startRpcPi(world: TestWorld, providerUrl: string, providerExtension: string): RpcHarness {
	const child = spawn("pi", [
		"--mode", "rpc",
		"--session-dir", world.piSessionDir,
		"--session-id", "rpc-session",
		"--provider", "herdr-scripted",
		"--model", "scripted-model",
		"--no-extensions",
		"--no-skills",
		"--no-prompt-templates",
		"--no-themes",
		"--no-context-files",
		"--no-tools",
		"--offline",
		"--extension", extensionDir,
		"--extension", providerExtension,
	], {
		cwd: world.root,
		env: {
			...process.env,
			...world.env,
			PI_CODING_AGENT_DIR: world.piAgentDir,
			PI_OFFLINE: "1",
			PI_TELEMETRY: "0",
			HERDR_TEST_PROVIDER_BASE_URL: providerUrl,
		},
		stdio: ["pipe", "pipe", "pipe"],
	});
	const records: any[] = [];
	let buffer = "";
	let stderrText = "";
	child.stdout.on("data", (chunk: Buffer) => {
		buffer += chunk.toString("utf8");
		let newline = buffer.indexOf("\n");
		while (newline >= 0) {
			const line = buffer.slice(0, newline).replace(/\r$/, "");
			buffer = buffer.slice(newline + 1);
			newline = buffer.indexOf("\n");
			if (!line.trim()) continue;
			try { records.push(JSON.parse(line)); }
			catch { records.push({ type: "invalid-json", line }); }
		}
	});
	child.stderr.on("data", (chunk: Buffer) => { stderrText += chunk.toString("utf8"); });

	const waitForRecord = (predicate: (record: any) => boolean, label: string) => waitFor(
		() => records.some(predicate) || child.exitCode !== null,
		label,
	).then(() => {
		const found = records.find(predicate);
		if (!found) throw new Error(`Pi exited before ${label}: ${stderrText}`);
		return found;
	});

	let requestNumber = 0;
	return {
		child,
		records,
		stderr: () => stderrText,
		sendPrompt: async (text: string) => {
			const id = `prompt-${++requestNumber}`;
			const response = waitForRecord((record) => record.type === "response" && record.id === id, `RPC response ${id}`);
			child.stdin.write(`${JSON.stringify({ id, type: "prompt", message: text })}\n`);
			const value = await response;
			assert.equal(value.success, true, value.error ?? stderrText);
		},
		waitForEvent: async (type: string, count: number) => {
			await waitFor(() => records.filter((record) => record.type === type).length >= count || child.exitCode !== null, `${type} event ${count}`);
			assert.ok(records.filter((record) => record.type === type).length >= count, `Pi exited before ${type}: ${stderrText}`);
			const extensionError = records.find((record) => record.type === "extension_error");
			assert.equal(extensionError, undefined, extensionError?.error ?? stderrText);
		},
		close: async () => {
			if (child.exitCode !== null) return;
			child.stdin.end();
			await new Promise<void>((resolve, reject) => {
				const timer = setTimeout(() => {
					child.kill("SIGTERM");
					reject(new Error(`Pi RPC process did not exit: ${stderrText}`));
				}, WAIT_MS);
				child.once("close", () => { clearTimeout(timer); resolve(); });
			});
		},
	};
}

async function startScriptedProvider() {
	let requestCount = 0;
	let resolveFirstRequest!: () => void;
	let releaseFirst!: () => void;
	const firstRequest = new Promise<void>((resolve) => { resolveFirstRequest = resolve; });
	const firstGate = new Promise<void>((resolve) => { releaseFirst = resolve; });
	const server = http.createServer((request, response) => {
		request.resume();
		request.on("end", async () => {
			requestCount += 1;
			const current = requestCount;
			if (current === 1) resolveFirstRequest();
			if (current === 1) await firstGate;
			const text = `Scripted settled response ${current}: work complete; present state ready.`;
			const common = { id: `scripted-${current}`, object: "chat.completion.chunk", created: 1, model: "scripted-model" };
			response.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache", connection: "keep-alive" });
			response.write(`data: ${JSON.stringify({ ...common, choices: [{ index: 0, delta: { role: "assistant", content: text }, finish_reason: null }] })}\n\n`);
			response.write(`data: ${JSON.stringify({ ...common, choices: [{ index: 0, delta: {}, finish_reason: "stop" }], usage: { prompt_tokens: 12, completion_tokens: 9, total_tokens: 21 } })}\n\n`);
			response.end("data: [DONE]\n\n");
		});
	});
	await new Promise<void>((resolve, reject) => {
		server.once("error", reject);
		server.listen(0, "127.0.0.1", resolve);
	});
	const address = server.address();
	assert.ok(address && typeof address === "object");
	return {
		url: `http://127.0.0.1:${address.port}/v1`,
		firstRequest,
		releaseFirst,
		count: () => requestCount,
		close: async () => new Promise<void>((resolve) => server.close(() => resolve())),
	};
}

test("a temporary Pi RPC session publishes only settled nonblank recaps with publication-time membership", async () => {
	const world = await createWorld();
	const herdr = world as TestWorld & { snapshot: any; calls: any[] };
	const provider = await startScriptedProvider();
	const providerExtension = path.join(world.root, "scripted-provider.mjs");
	writeFileSync(providerExtension, `export default function (pi) {
  pi.registerProvider("herdr-scripted", {
    name: "Scripted test provider",
    api: "openai-completions",
    baseUrl: process.env.HERDR_TEST_PROVIDER_BASE_URL,
    apiKey: "test-only",
    models: [{
      id: "scripted-model", name: "Scripted test model", reasoning: false, input: ["text"],
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 4096, maxTokens: 128,
    }],
  });
}`);

	const rpc = startRpcPi(world, provider.url, providerExtension);
	try {
		const eventOne = rpc.records.filter((record) => record.type === "agent_settled").length + 1;
		await rpc.sendPrompt("RPC request one: verify the current prompt and recap stay separate.");
		await provider.firstRequest;
		assert.equal(promptRecord(world.dataRoot, "rpc-session").text, "RPC request one: verify the current prompt and recap stay separate.");
		assert.equal(readTrace(world.tracePath).some((line) => line.startsWith("cli prepare ")), false);
		assert.equal(readTrace(world.tracePath).some((line) => line.startsWith("cli publish ")), false);
		assert.equal(herdr.calls.length, 0, "no membership lookup or wake-up occurs while the response is streaming");

		provider.releaseFirst();
		await rpc.waitForEvent("agent_settled", eventOne);
		await waitFor(() => herdr.calls.some((call) => call.method === "plugin.action.invoke"), "the first publication wake-up");
		const firstRecap = latestPublished(world.dataRoot, "rpc-session");
		assert.equal(firstRecap.summary, SUCCESS_SUMMARY);
		assert.equal(firstRecap.workspace_id, "workspace-exact");
		assert.equal(firstRecap.pane_id, "exact-pane");
		const firstWake = herdr.calls.find((call: any) => call.method === "plugin.action.invoke");
		assert.equal(firstWake.params.action_id, "overview.reconcile");
		assert.equal(firstWake.publishedRecord.record_id, firstRecap.record_id);

		// A later real RPC prompt updates the current prompt; absent native membership is not guessed from UI focus.
		herdr.snapshot = { protocol: 22, focused_pane_id: "ui-focused-pane", panes: [{ pane_id: "other-pane", workspace_id: "wrong-workspace" }] };
		const eventTwo = rpc.records.filter((record) => record.type === "agent_settled").length + 1;
		await rpc.sendPrompt("RPC request two: no native pane membership is available.");
		await rpc.waitForEvent("agent_settled", eventTwo);
		await waitFor(() => herdr.calls.filter((call) => call.method === "plugin.action.invoke").length === 2, "the second publication wake-up");
		const secondRecap = latestPublished(world.dataRoot, "rpc-session");
		assert.notEqual(secondRecap.record_id, firstRecap.record_id);
		assert.equal(Object.hasOwn(secondRecap, "workspace_id"), false);
		assert.equal(promptRecord(world.dataRoot, "rpc-session").text, "RPC request two: no native pane membership is available.");
		assert.equal(promptRecord(world.dataRoot, "rpc-session").working, false);

		// Blank backend output is a failed T1 attempt: it cannot replace the latest success or wake Herdr.
		world.setBackendMode("blank");
		const eventThree = rpc.records.filter((record) => record.type === "agent_settled").length + 1;
		await rpc.sendPrompt("RPC request three: the recap backend will return blank output.");
		await rpc.waitForEvent("agent_settled", eventThree);
		await waitFor(() => sourceEntry(world.dataRoot, "rpc-session")?.last_attempt_id !== secondRecap.record_id, "the failed T1 attempt");
		const latestEntry = sourceEntry(world.dataRoot, "rpc-session");
		assert.equal(latestEntry.latest_success_id, secondRecap.record_id);
		assert.equal(readRecord(world.dataRoot, latestEntry.last_attempt_id).status, "failed");
		assert.equal(herdr.calls.filter((call) => call.method === "plugin.action.invoke").length, 2);
		assert.equal(herdr.calls.filter((call) => call.method === "session.snapshot").length, 2);
		assert.equal(promptRecord(world.dataRoot, "rpc-session").working, false);

		const trace = readTrace(world.tracePath);
		const prepareIndices = trace.flatMap((line, index) => line.startsWith("cli prepare ") ? [index] : []);
		assert.equal(prepareIndices.length, 3);
		for (const index of prepareIndices.slice(0, 2)) {
			assert.equal(trace[index + 1], "herdr session.snapshot");
			assert.match(trace[index + 2], /^cli publish /);
			assert.equal(trace[index + 3], "herdr plugin.action.invoke");
		}
		assert.notEqual(trace[prepareIndices[2] + 1], "herdr session.snapshot");
	} finally {
		provider.releaseFirst();
		await rpc.close().catch(() => {});
		await provider.close();
		await world.close();
	}
});
