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
import { readPiSessionFields, piSessionFile } from "../../../../dot_local/share/herdr-overview/src/pi-session-store.mjs";
import { writePiMetadata, retirePiMetadata } from "./helpers.ts";

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
	setCurrentPane(pane: { pane_id: string; workspace_id: string } | undefined): void;
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
		"#!/bin/sh\nprintf 'cli %s\\n' \"$*\" >> \"$HERDR_OVERVIEW_TEST_TRACE\"\nif [ \"$1\" = config ]; then\n  \"$SESSION_RECAP_REAL_BIN\" \"$@\"\n  status=$?\n  printf 'cli done %s %s\\n' \"$*\" \"$status\" >> \"$HERDR_OVERVIEW_TEST_TRACE\"\n  exit \"$status\"\nfi\nexec \"$SESSION_RECAP_REAL_BIN\" \"$@\"\n",
	);
	chmodSync(spyCliPath, 0o755);

	const configPath = path.join(configDir, "config.toml");
	const setBackendMode = (mode: "success" | "blank" | "nonzero") => {
		const command = [process.env.PYTHON ?? "python3", fakeBackend, mode];
		writeFileSync(configPath, `auto_publish = true\ncommand = ${JSON.stringify(command)}\n`);
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
	let currentPane: { pane_id: string; workspace_id: string } | undefined = {
		pane_id: "exact-pane",
		workspace_id: "workspace-exact",
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
				} else if (request.method === "pane.current") {
					call.currentPane = request.params?.caller_pane_id === "exact-pane" ? currentPane : undefined;
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
				const result = request.method === "session.snapshot"
					? { snapshot: currentSnapshot }
					: request.method === "pane.current"
						? { type: "pane_current", pane: request.params?.caller_pane_id === "exact-pane" ? currentPane : undefined }
						: {};
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
            HERDR_ENV: "0",
		},
		setBackendMode,
		setCurrentPane: (pane) => { currentPane = pane; },
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
 "HERDR_ENV",
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

function shellQuote(value: string): string {
	return `'${value.replace(/'/g, "'\\''")}'`;
}

function registeredHandlers(): Map<string, (...args: any[]) => any> {
	const handlers = new Map<string, (...args: any[]) => any>();
	extension({ events: {on(){},emit(){}}, on: (event: string, handler: (...args: any[]) => any) => handlers.set(event, handler) } as any);
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

test("managed default-off settles the prompt without preparing or waking a recap", async () => {
	const world = await createWorld();
	writeFileSync(path.join(world.root, "config", "session-recap", "config.toml"), "auto_publish = false\n");
	try {
		await withProcessEnv(world.env, async () => {
			const handlers = registeredHandlers();
			await handlers.get("input")!(
				{ type: "input", source: "interactive", text: "Keep the current prompt visible." },
				fakeContext("default-off-session", "tui", false, []).ctx,
			);
			await handlers.get("agent_settled")!(
				{}, fakeContext("default-off-session", "tui", true, responseEntry("A settled reply without a recap.")).ctx,
			);
			await waitFor(() => readTrace(world.tracePath).includes("cli done config auto-publish 0"),
				"the completed automatic recap policy check", 1_500);
			assert.equal(promptRecord(world.dataRoot, "default-off-session").working, false);
			assert.equal(existsSync(path.join(world.dataRoot, "latest.json")), false);
			assert.equal(existsSync(world.capturePath), false);
			assert.deepEqual(world.calls.map((call) => call.method), ["pane.current"]);
			assert.equal(readTrace(world.tracePath).some((line) => line.startsWith("cli prepare ")), false);
			assert.equal(readTrace(world.tracePath).some((line) => line.startsWith("cli publish ")), false);
		});
	} finally {
		await world.close();
	}
});

test("interactive prompt stays separate; settled publication rechecks exact pane membership", async () => {
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
			assert.equal(promptRecord(world.dataRoot, "interactive-session").pane_id, "exact-pane");
			assert.equal(readTrace(world.tracePath).filter((line) => line.startsWith("cli prompt set ")).length, 1);
			assert.deepEqual(readTrace(world.tracePath).map((line) => line.split(" ").slice(0, 2).join(" ")), [
				"herdr pane.current",
				"cli prompt",
			]);
			assert.deepEqual(world.calls[0].params, { caller_pane_id: "exact-pane" });

			const beforeIdle = handlers.get("agent_settled")!(
				{},
				fakeContext("interactive-session", "tui", false, responseEntry("Settled assistant answer.")).ctx,
			);
			assert.equal(beforeIdle, undefined);
			assert.deepEqual(readTrace(world.tracePath).map((line) => line.split(" ").slice(0, 2).join(" ")), [
				"herdr pane.current",
				"cli prompt",
			]);

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
			assert.equal(world.calls.filter((call) => call.method === "pane.current").length, 3);
			assert.notEqual(prompt.text, recap.summary);
			assert.match(readFileSync(world.capturePath, "utf8"), /Settled assistant answer\./);
			assert.equal(world.calls.find((call) => call.method === "plugin.action.invoke").params.action_id, "overview.reconcile");
			assert.equal(world.calls.find((call) => call.method === "plugin.action.invoke").publishedRecord.record_id, recap.record_id);

			const order = readTrace(world.tracePath);
			const preparedAt = order.findIndex((line) => line.startsWith("cli prepare "));
			assert.ok(preparedAt >= 0);
			assert.equal(order[preparedAt + 1], "herdr pane.current");
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

test("first Pi response moved before settlement rekeys prompt and prepared recap", async () => {
	const world = await createWorld();
	try {
		await withProcessEnv(world.env, async () => {
			const handlers = registeredHandlers();
			const text = "First request before a native pane move.";
			await handlers.get("input")!(
				{ type: "input", source: "interactive", text },
				fakeContext("first-move-session", "tui", false, []).ctx,
			);
			assert.equal(promptRecord(world.dataRoot, "first-move-session").pane_id, "exact-pane");
			world.setCurrentPane({ pane_id: "moved-pane", workspace_id: "workspace-new" });
			await handlers.get("agent_settled")!(
				{}, fakeContext("first-move-session", "tui", true, responseEntry("First completed response.")).ctx,
			);
			await waitFor(() => existsSync(path.join(world.dataRoot, "latest.json"))
				&& latestPublished(world.dataRoot, "first-move-session"), "first moved publication");
			const prompt = promptRecord(world.dataRoot, "first-move-session");
			const recap = latestPublished(world.dataRoot, "first-move-session");
			assert.equal(prompt.text, text);
			assert.equal(prompt.pane_id, "moved-pane");
			assert.equal(prompt.working, false);
			assert.equal(recap.pane_id, "moved-pane");
			assert.equal(recap.workspace_id, "workspace-new");
			await waitFor(() => world.calls.some((call) => call.method === "plugin.action.invoke"), "first moved overview wake-up");
			assert.equal(world.calls.find((call) => call.method === "plugin.action.invoke")?.publishedRecord?.record_id, recap.record_id);
		});
	} finally {
		await world.close();
	}
});

test("overlapping settled responses publish in event order when an earlier prompt settle is slow", async () => {
	const world = await createWorld();
	const markerPath = path.join(world.root, "first-settle-started");
	const delayedCliPath = path.join(world.root, "delayed-session-recap");
	const spyCliPath = path.join(world.root, "session-recap-spy");
	writeFileSync(delayedCliPath, [
		"#!/bin/sh",
		`if [ \"$1\" = prompt ] && [ \"$2\" = settle ] && [ ! -e ${shellQuote(markerPath)} ]; then`,
		`  : > ${shellQuote(markerPath)}`,
		"  sleep 0.3",
		"fi",
		`exec ${shellQuote(spyCliPath)} \"$@\"`,
	].join("\n") + "\n");
	chmodSync(delayedCliPath, 0o755);
	const backendPath = path.join(world.root, "ordered-backend.mjs");
	writeFileSync(backendPath, `let prompt = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => { prompt += chunk; });
process.stdin.on("end", () => {
  if (prompt.includes("First settled response.")) process.stdout.write("Recap for first response.\\n");
  else if (prompt.includes("Second settled response.")) process.stdout.write("Recap for second response.\\n");
  else process.exitCode = 7;
});
`);
	writeFileSync(
		path.join(world.root, "config", "session-recap", "config.toml"),
		`auto_publish = true\ncommand = ${JSON.stringify([process.execPath, backendPath])}\n`,
	);

	try {
		await withProcessEnv({ ...world.env, SESSION_RECAP_BIN: delayedCliPath }, async () => {
			const handlers = registeredHandlers();
			const input = handlers.get("input")!;
			await input({ type: "input", source: "interactive", text: "First request." },
				fakeContext("ordered-session", "tui", false, []).ctx);
			const firstSettled = handlers.get("agent_settled")!(
				{}, fakeContext("ordered-session", "tui", true, responseEntry("First settled response.")).ctx,
			) as Promise<void>;
			await waitFor(() => existsSync(markerPath), "the first delayed prompt settle");

			await input({ type: "input", source: "interactive", text: "Second request." },
				fakeContext("ordered-session", "tui", false, []).ctx);
			await handlers.get("agent_settled")!(
				{}, fakeContext("ordered-session", "tui", true, responseEntry("Second settled response.")).ctx,
			);
			await firstSettled;
			await waitFor(
				() => world.calls.filter((call) => call.method === "plugin.action.invoke").length === 2,
				"both ordered recap publications",
			);

			assert.equal(latestPublished(world.dataRoot, "ordered-session").summary, "Recap for second response.");
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

function startRpcPi(world: TestWorld, providerUrl: string, providerExtension: string, sessionId = "rpc-session"): RpcHarness {
	const child = spawn("pi", [
		"--mode", "rpc",
		"--session-dir", world.piSessionDir,
		"--session-id", sessionId,
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

function scriptedProviderExtension(world: TestWorld): string {
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
	return providerExtension;
}

test("private bridge rejects duplicates, conflicts and invalid digests; retirement is compare-owned", async () => {
	const world = await createWorld();
	try { await withProcessEnv(world.env, async () => {
		const sessionId = "11111111-1111-4111-8111-111111111111";
		const record = { schemaVersion: 1, socketPath: world.env.HERDR_SOCKET_PATH, terminalId: "terminal-exact", paneId: "old-pane", sessionId, sessionName: "Full stable synthetic name", publisherPid: process.pid, generation: "new-owner" };
		const file = writePiMetadata(record);
		const snapshot = { protocol: 22, panes: [{ pane_id: "new-pane", terminal_id: "terminal-exact" }] };
		const read = () => readPiSessionFields(snapshot, { socketPath: record.socketPath, env: world.env }).piSessionsByPaneId;
		assert.equal(read()["new-pane"].digest.reason, "missing");
		const dir = path.join(world.env.HOME, ".pi/session-search/digests"); mkdirSync(dir, { recursive: true });
		writeFileSync(path.join(dir, sessionId + ".json"), JSON.stringify({ schemaVersion: 1, body: "POSITIVE NEW DIGEST", generatedAt: "2026-01-01T00:00:00Z" }));
		assert.equal(read()["new-pane"].digest.body, "POSITIVE NEW DIGEST");
		retirePiMetadata(file, "old-owner"); assert.ok(existsSync(file));
		writeFileSync(path.join(path.dirname(file), "duplicate.json"), JSON.stringify(record)); assert.deepEqual(read(), {}); rmSync(path.join(path.dirname(file), "duplicate.json"));
		(snapshot.panes[0] as any).agent_session = "22222222-2222-4222-8222-222222222222"; assert.deepEqual(read(), {}); delete (snapshot.panes[0] as any).agent_session;
		writeFileSync(path.join(dir, sessionId + ".json"), JSON.stringify({ schemaVersion: 1, body: "NEGATIVE INVALID", generatedAt: "bad" })); assert.equal(read()["new-pane"].digest.body, null);
		writePiMetadata({ ...record, publisherPid: 2147483647 }); assert.deepEqual(read(), {});
		writePiMetadata(record); retirePiMetadata(file, "new-owner"); assert.equal(existsSync(file), false);
	}); } finally { await world.close(); }
});

test("disposable Pi replacement and reload publish only the current caller-bound UUID", async () => {
	const world = await createWorld();
	const herdr = world as TestWorld & { snapshot: any };
	herdr.snapshot.panes[0].terminal_id = "terminal-exact";
	herdr.snapshot.panes[1].terminal_id = "terminal-focused";
	const provider = await startScriptedProvider();
	const providerFile = scriptedProviderExtension(world);
	writeFileSync(providerFile, readFileSync(providerFile, "utf8").replace('export default function (pi) {', 'export default function (pi) { pi.registerCommand("fixture-clear-name", { description: "Clear name fixture", handler: async () => { pi.setSessionName(""); } }); pi.registerCommand("fixture-reload", { description: "Reload fixture", handler: async (_args, ctx) => { await ctx.reload(); } }); pi.on("session_start", () => pi.setSessionName("Synthetic full stable lifecycle name"));'));
	const firstId = "11111111-1111-4111-8111-111111111111";
	const rpc = startRpcPi(world, provider.url, providerFile, firstId);
	const file = piSessionFile(world.env.HERDR_SOCKET_PATH, "terminal-exact", world.env);
	const request = async (type: string, fields = {}) => {
		const id = `${type}-${Date.now()}`;
		rpc.child.stdin.write(JSON.stringify({ id, type, ...fields }) + "\n");
		await waitFor(() => rpc.records.some(record => record.id === id), type);
		assert.equal(rpc.records.find(record => record.id === id).success, true, JSON.stringify(rpc.records.find(record => record.id === id)));
	};
	try {
		await waitFor(() => existsSync(file), "initial bridge");
		assert.equal(readJson(file).sessionId, firstId);
		for (const name of ["Real RPC stable name", "Replacement RPC stable name"]) {
			await request("set_session_name", { name });
			await waitFor(() => readJson(file).sessionName === name, "public name event bridge refresh");
		}
		await waitFor(() => herdr.calls.filter((call: any) => call.params?.action_id === "overview.refresh_names").length >= 2, "passive name wake-up");
		await rpc.sendPrompt("/fixture-clear-name");
		await waitFor(() => readJson(file).sessionName === null, "public cleared name event");
		assert.equal(readJson(file).sessionId, firstId);
		assert.equal(provider.count(), 0);
		assert.equal(existsSync(world.capturePath), false);
		assert.equal(readTrace(world.tracePath).some(line => line.startsWith("cli ")), false);
		const dir = path.join(world.env.HOME, ".pi/session-search/digests"); mkdirSync(dir, { recursive: true });
		writeFileSync(path.join(dir, firstId + ".json"), JSON.stringify({ schemaVersion: 1, body: "NEGATIVE OLD SESSION", generatedAt: "2026-01-01T00:00:00Z" }));
		await request("new_session");
		await waitFor(() => existsSync(file) && readJson(file).sessionId !== firstId, "replacement bridge");
		const newId = readJson(file).sessionId;
		assert.equal(readPiSessionFields(herdr.snapshot, { socketPath: world.env.HERDR_SOCKET_PATH, env: world.env }).piSessionsByPaneId["exact-pane"].digest.body, null);
		writeFileSync(path.join(dir, newId + ".json"), JSON.stringify({ schemaVersion: 1, body: "POSITIVE NEW SESSION", generatedAt: "2026-01-02T00:00:00Z" }));
		assert.equal(readPiSessionFields(herdr.snapshot, { socketPath: world.env.HERDR_SOCKET_PATH, env: world.env }).piSessionsByPaneId["exact-pane"].digest.body, "POSITIVE NEW SESSION");
		assert.equal(readPiSessionFields(herdr.snapshot, { socketPath: world.env.HERDR_SOCKET_PATH, env: world.env }).piSessionsByPaneId["ui-focused-pane"], undefined);
		const oldGeneration = readJson(file).generation;
		await rpc.sendPrompt("/fixture-reload");
		await waitFor(() => existsSync(file) && readJson(file).generation !== oldGeneration && readJson(file).sessionId === newId, "reload bridge");
		assert.equal(readJson(file).sessionName, "Synthetic full stable lifecycle name");
		await rpc.close(); await waitFor(() => !existsSync(file), "owned retirement");
	} finally { provider.releaseFirst(); await rpc.close(); await provider.close(); await world.close(); }
});

test("a temporary Pi RPC reply settles without recap publication when managed default is off", async () => {
	const world = await createWorld();
	writeFileSync(path.join(world.root, "config", "session-recap", "config.toml"), "auto_publish = false\n");
	const herdr = world as TestWorld & { calls: any[] };
	const provider = await startScriptedProvider();
	const rpc = startRpcPi(world, provider.url, scriptedProviderExtension(world));
	try {
		const settled = rpc.records.filter((record) => record.type === "agent_settled").length + 1;
		await rpc.sendPrompt("RPC default-off request: preserve the prompt without a recap.");
		await provider.firstRequest;
		provider.releaseFirst();
		await rpc.waitForEvent("agent_settled", settled);
		await waitFor(() => readTrace(world.tracePath).includes("cli done config auto-publish 0"),
			"the completed default-off policy check");
		assert.equal(promptRecord(world.dataRoot, "rpc-session").working, false);
		assert.equal(existsSync(path.join(world.dataRoot, "latest.json")), false);
		assert.equal(existsSync(world.capturePath), false);
		assert.deepEqual(herdr.calls.map((call: any) => call.method), ["pane.current"]);
		assert.equal(readTrace(world.tracePath).some((line) => line.startsWith("cli prepare ")), false);
		assert.equal(readTrace(world.tracePath).some((line) => line.startsWith("cli publish ")), false);
	} finally {
		provider.releaseFirst();
		await rpc.close().catch(() => {});
		await provider.close();
		await world.close();
	}
});

test("a temporary Pi RPC session publishes only settled nonblank recaps with publication-time membership", async () => {
	const world = await createWorld();
	const herdr = world as TestWorld & { snapshot: any; calls: any[] };
	const provider = await startScriptedProvider();
	const providerExtension = scriptedProviderExtension(world);
	const rpc = startRpcPi(world, provider.url, providerExtension);
	try {
		const eventOne = rpc.records.filter((record) => record.type === "agent_settled").length + 1;
		await rpc.sendPrompt("RPC request one: verify the current prompt and recap stay separate.");
		await provider.firstRequest;
		assert.equal(promptRecord(world.dataRoot, "rpc-session").text, "RPC request one: verify the current prompt and recap stay separate.");
		assert.equal(readTrace(world.tracePath).some((line) => line.startsWith("cli prepare ")), false);
		assert.equal(readTrace(world.tracePath).some((line) => line.startsWith("cli publish ")), false);
		assert.deepEqual(herdr.calls.map((call: any) => call.method), ["pane.current"],
			"input resolves the caller pane, but no publication lookup or wake-up occurs while the response is streaming");

		provider.releaseFirst();
		await rpc.waitForEvent("agent_settled", eventOne);
		await waitFor(() => herdr.calls.some((call) => call.method === "plugin.action.invoke"), "the first publication wake-up");
		const firstRecap = latestPublished(world.dataRoot, "rpc-session");
		assert.equal(firstRecap.summary, SUCCESS_SUMMARY);
		assert.equal(firstRecap.workspace_id, "workspace-exact");
		assert.equal(firstRecap.pane_id, "exact-pane");
		assert.equal(promptRecord(world.dataRoot, "rpc-session").pane_id, "exact-pane");
		const firstWake = herdr.calls.find((call: any) => call.method === "plugin.action.invoke");
		assert.equal(firstWake.params.action_id, "overview.reconcile");
		assert.equal(firstWake.publishedRecord.record_id, firstRecap.record_id);

		// A successful caller-aware lookup follows the running pane after Herdr rekeys it.
		herdr.snapshot = { protocol: 22, focused_pane_id: "ui-focused-pane", panes: [{ pane_id: "rekeyed-pane", workspace_id: "workspace-after-move" }] };
		assert.equal(herdr.snapshot.panes.some((pane: any) => pane.pane_id === "exact-pane"), false);
		herdr.setCurrentPane({ pane_id: "rekeyed-pane", workspace_id: "workspace-after-move" });
		const eventTwo = rpc.records.filter((record) => record.type === "agent_settled").length + 1;
		await rpc.sendPrompt("RPC request two: the pane moved and its native ID changed.");
		await rpc.waitForEvent("agent_settled", eventTwo);
		await waitFor(() => herdr.calls.filter((call) => call.method === "plugin.action.invoke").length === 2, "the second publication wake-up");
		const secondRecap = latestPublished(world.dataRoot, "rpc-session");
		assert.notEqual(secondRecap.record_id, firstRecap.record_id);
		assert.equal(secondRecap.workspace_id, "workspace-after-move");
		const moveLookups = herdr.calls.filter((call) => call.method === "pane.current").slice(3, 6);
		assert.equal(moveLookups.length, 3, "input, preparation, and publication resolve through the inherited caller ID");
		assert.ok(moveLookups.every((call) => call.params.caller_pane_id === "exact-pane"));
		assert.ok(moveLookups.every((call) => call.currentPane.pane_id === "rekeyed-pane"));
		assert.equal(promptRecord(world.dataRoot, "rpc-session").text, "RPC request two: the pane moved and its native ID changed.");
		assert.equal(promptRecord(world.dataRoot, "rpc-session").pane_id, "rekeyed-pane");
		assert.equal(secondRecap.pane_id, "rekeyed-pane");
		assert.equal(promptRecord(world.dataRoot, "rpc-session").working, false);

		// Missing caller membership publishes without guessing from the UI-focused pane.
		herdr.snapshot = { protocol: 22, focused_pane_id: "ui-focused-pane", panes: [{ pane_id: "ui-focused-pane", workspace_id: "wrong-workspace" }] };
		herdr.setCurrentPane(undefined);
		const eventThree = rpc.records.filter((record) => record.type === "agent_settled").length + 1;
		await rpc.sendPrompt("RPC request three: no native pane membership is available.");
		await rpc.waitForEvent("agent_settled", eventThree);
		await waitFor(() => herdr.calls.filter((call) => call.method === "plugin.action.invoke").length === 3, "the third publication wake-up");
		const thirdRecap = latestPublished(world.dataRoot, "rpc-session");
		assert.notEqual(thirdRecap.record_id, secondRecap.record_id);
		assert.equal(Object.hasOwn(thirdRecap, "workspace_id"), false);
		assert.equal(Object.hasOwn(thirdRecap, "pane_id"), false);
		assert.equal(promptRecord(world.dataRoot, "rpc-session").text, "RPC request three: no native pane membership is available.");
		assert.equal(Object.hasOwn(promptRecord(world.dataRoot, "rpc-session"), "pane_id"), false);
		assert.equal(promptRecord(world.dataRoot, "rpc-session").working, false);

		// Blank backend output is a failed T1 attempt: it cannot replace the latest success or wake Herdr.
		world.setBackendMode("blank");
		const eventFour = rpc.records.filter((record) => record.type === "agent_settled").length + 1;
		await rpc.sendPrompt("RPC request four: the recap backend will return blank output.");
		await rpc.waitForEvent("agent_settled", eventFour);
		await waitFor(() => sourceEntry(world.dataRoot, "rpc-session")?.last_attempt_id !== thirdRecap.record_id, "the failed T1 attempt");
		const latestEntry = sourceEntry(world.dataRoot, "rpc-session");
		assert.equal(latestEntry.latest_success_id, thirdRecap.record_id);
		assert.equal(readRecord(world.dataRoot, latestEntry.last_attempt_id).status, "failed");
		assert.equal(herdr.calls.filter((call) => call.method === "plugin.action.invoke").length, 3);
		assert.equal(herdr.calls.filter((call) => call.method === "pane.current").length, 11);
		assert.ok(herdr.calls.every((call) => call.method !== "session.snapshot"), "never fall back to snapshots or UI focus");
		assert.equal(promptRecord(world.dataRoot, "rpc-session").working, false);

		const trace = readTrace(world.tracePath);
		const promptSetIndices = trace.flatMap((line, index) => line.startsWith("cli prompt set ") ? [index] : []);
		assert.equal(promptSetIndices.length, 4);
		for (const index of promptSetIndices) assert.equal(trace[index - 1], "herdr pane.current");
		assert.ok(trace.some((line) => line === "cli prompt set --session-id rpc-session --pane-id rekeyed-pane"));
		const prepareIndices = trace.flatMap((line, index) => line.startsWith("cli prepare ") ? [index] : []);
		assert.equal(prepareIndices.length, 4);
		for (const index of prepareIndices.slice(0, 3)) {
			assert.equal(trace[index + 1], "herdr pane.current");
			assert.match(trace[index + 2], /^cli publish /);
			assert.equal(trace[index + 3], "herdr plugin.action.invoke");
		}
		assert.notEqual(trace[prepareIndices[3] + 1], "herdr pane.current");
	} finally {
		provider.releaseFirst();
		await rpc.close().catch(() => {});
		await provider.close();
		await world.close();
	}
});

test("real print and JSON children with inherited Herdr env never contact or claim the parent binding", async () => {
	const world = await createWorld();
	const herdr = world as TestWorld & { calls: any[] };
	const provider = await startScriptedProvider();
	provider.releaseFirst();
	const providerFile = scriptedProviderExtension(world);
	try {
		for (const mode of ["text", "json"]) {
			const child = spawn("pi", ["--print", "--mode", mode, "--no-session", "--no-extensions", "--no-skills", "--no-context-files", "--no-tools", "--offline", "--extension", extensionDir, "--extension", providerFile, "--provider", "herdr-scripted", "--model", "scripted-model", "Synthetic child reply"], {
				cwd: world.root, env: { ...process.env, ...world.env, PI_CODING_AGENT_DIR: world.piAgentDir, HERDR_TEST_PROVIDER_BASE_URL: provider.url }, stdio: ["ignore", "pipe", "pipe"],
			});
			let stderr = ""; child.stdout.resume(); child.stderr.on("data", data => { stderr += data; });
			const code = await new Promise<number | null>((resolve, reject) => { child.once("error", reject); child.once("exit", resolve); });
			assert.equal(code, 0, stderr);
			assert.deepEqual(herdr.calls, []);
			assert.equal(existsSync(path.join(world.env.HOME, ".local/state", "herdr-overview", "pi-sessions")), false);
			assert.equal(readTrace(world.tracePath).some(line => line.startsWith("cli ")), false);
		}
	} finally { await provider.close(); await world.close(); }
});

test('actual public wait edges pair one native contribution and clear only owned reason across lifecycle', async () => {
 const {registerQuestionWait}=await import('./question-wait.ts');
 const {EventEmitter}=await import('node:events');
 const world=await createWorld();
 try {
  world.snapshot={protocol:22,panes:[{pane_id:'exact-pane',terminal_id:'terminal-question',workspace_id:'workspace-exact'}]};
  world.setCurrentPane({pane_id:'exact-pane',workspace_id:'workspace-exact'});
  await withProcessEnv({...world.env,HERDR_ENV:'1'},async()=>{
   const handlers=new Map<string,any>(),bus=new EventEmitter(),edges:any[]=[];
   bus.on('herdr:blocked',data=>edges.push(data));
   registerQuestionWait({events:{on:(name:string,fn:any)=>bus.on(name,fn),emit:(name:string,data:any)=>bus.emit(name,data)},on:(name:string,fn:any)=>handlers.set(name,fn)} as any);
   const ctx={mode:'tui',hasUI:true,sessionManager:{getSessionId:()=> 'question-session'}} as any;
   await handlers.get('session_start')({},ctx);
   bus.emit('rpiv:ask-user:blocked',{active:true});bus.emit('rpiv:ask-user:blocked',{active:true});
   await waitFor(()=>world.calls.some(c=>c.method==='pane.report_metadata'&&c.params.state_labels?.blocked==='Awaiting answer'),'owned question label');
   bus.emit('rpiv:ask-user:blocked',{active:false});bus.emit('rpiv:ask-user:blocked',{active:false});
   await handlers.get('session_shutdown')({reason:'reload'},ctx);
   assert.deepEqual(edges,[{active:true,label:'Awaiting answer'},{active:false,label:'Awaiting answer'}]);
   const reports=world.calls.filter(c=>c.method==='pane.report_metadata');
   assert.ok(reports.length>=3);assert.ok(reports.every(c=>c.params.source==='herdr:overview-question'&&c.params.applies_to_source==='herdr:pi'));
   assert.equal(reports.at(-1).params.clear_state_labels,true);
   assert.ok(reports.every((c,i)=>!i||c.params.seq>reports[i-1].params.seq));
   assert.ok(!world.calls.some(c=>c.method==='pane.report_agent'||c.method==='pane.clear_agent_authority'));
   bus.emit('rpiv:ask-user:blocked',{active:true});assert.equal(edges.length,2);
  });
 } finally {await world.close();}
});
