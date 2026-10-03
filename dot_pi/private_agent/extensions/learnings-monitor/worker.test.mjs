import assert from "node:assert/strict";
import { createServer } from "node:http";
import fs from "node:fs/promises";
import { existsSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import test from "node:test";
import { createPiCaptureBridge, isObserverSession, piSourceId } from "./capture.mjs";
import { reviewActivity } from "./core/index.mjs";
import { createLearningStore } from "./store.mjs";
import { createPiObserverRunner, getDefaultProviderExtensionLoadout, OBSERVER_SESSION_MARKER } from "./worker.mjs";

const moduleRoots = [
	...(process.env.NODE_PATH ?? "").split(path.delimiter).filter(Boolean),
	path.resolve(path.dirname(process.execPath), "../lib/node_modules"),
];
const sdkPath = moduleRoots
	.map((root) => path.join(root, "@earendil-works/pi-coding-agent", "dist", "index.js"))
	.find((filename) => existsSync(filename));
if (!sdkPath) throw new Error("Set NODE_PATH to the global node_modules directory containing @earendil-works/pi-coding-agent");
const packageRoot = path.dirname(path.dirname(sdkPath));
const piAiPath = path.join(packageRoot, "node_modules", "@earendil-works", "pi-ai", "dist", "index.js");
const sdk = await import(pathToFileURL(sdkPath).href);
const piAi = await import(pathToFileURL(piAiPath).href);

function emptyCost() {
	return { input: 0.001, output: 0.002, cacheRead: 0, cacheWrite: 0, total: 0.003 };
}

function makeAssistant(model) {
	return {
		role: "assistant",
		content: [],
		api: model.api,
		provider: model.provider,
		model: model.id,
		usage: {
			input: 11,
			output: 7,
			cacheRead: 0,
			cacheWrite: 0,
			totalTokens: 18,
			cost: emptyCost(),
		},
		stopReason: "pending",
		timestamp: Date.now(),
	};
}

function scriptedStream(model, options, respond) {
	const stream = piAi.createAssistantMessageEventStream();
	const partial = makeAssistant(model);
	stream.push({ type: "start", partial });
	Promise.resolve().then(() => respond({ model, options })).then((answer) => {
		if (answer.kind === "aborted") {
			partial.stopReason = "aborted";
			partial.errorMessage = "Scripted request aborted";
			stream.push({ type: "error", reason: "aborted", error: partial });
			stream.end(partial);
			return;
		}
		if (answer.kind === "tool") {
			const toolCall = { type: "toolCall", id: `scripted-call-${Date.now()}`, name: answer.name, arguments: answer.arguments };
			partial.content.push(toolCall);
			stream.push({ type: "toolcall_start", contentIndex: 0, partial });
			stream.push({ type: "toolcall_delta", contentIndex: 0, delta: JSON.stringify(toolCall.arguments), partial });
			stream.push({ type: "toolcall_end", contentIndex: 0, toolCall, partial });
			partial.stopReason = "toolUse";
			stream.push({ type: "done", reason: "toolUse", message: partial });
			stream.end(partial);
			return;
		}
		const text = answer.text ?? "{}";
		const block = { type: "text", text: "" };
		partial.content.push(block);
		stream.push({ type: "text_start", contentIndex: 0, partial });
		block.text = text;
		stream.push({ type: "text_delta", contentIndex: 0, delta: text, partial });
		stream.push({ type: "text_end", contentIndex: 0, content: text, partial });
		partial.stopReason = "stop";
		stream.push({ type: "done", reason: "stop", message: partial });
		stream.end(partial);
	}).catch((error) => {
		partial.stopReason = "error";
		partial.errorMessage = error.message;
		stream.push({ type: "error", reason: "error", error: partial });
		stream.end(partial);
	});
	return stream;
}

async function makeRuntime(agentDir, sourceId, respond) {
	const runtime = await sdk.ModelRuntime.create({
		authPath: path.join(agentDir, "missing-auth.json"),
		modelsPath: null,
		allowModelNetwork: false,
		refreshOnCreate: false,
	});
	runtime.registerProvider("scripted", {
		name: "Scripted observer provider",
		api: "openai-completions",
		baseUrl: "http://scripted.test/v1",
		apiKey: "scripted-test-key",
		models: ["reviewer-a", "reviewer-b"].map((id) => ({
			id,
			name: `Scripted ${id}`,
			api: "openai-completions",
			reasoning: false,
			input: ["text"],
			cost: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0 },
			contextWindow: 32_000,
			maxTokens: 2_000,
		})),
		streamSimple: (model, context, options) => scriptedStream(model, options, (streamOptions) => respond({
			...streamOptions,
			sourceId,
			context,
			lastUser: [...context.messages].reverse().find((message) => message.role === "user")?.content ?? "",
		})),
	});
	return runtime;
}

async function fixture(t, respond) {
	const root = await fs.mkdtemp(path.join(os.tmpdir(), "learnings-observer-worker-"));
	t.after(async () => fs.rm(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 10 }));
	const agentDir = path.join(root, "agent");
	const sessionDir = path.join(root, "sessions");
	const cwd = path.join(root, "workspace");
	await Promise.all([fs.mkdir(agentDir, { recursive: true }), fs.mkdir(sessionDir, { recursive: true }), fs.mkdir(cwd, { recursive: true })]);
	const store = createLearningStore({ root: path.join(root, "local-store") });
	const runner = createPiObserverRunner({
		sdk,
		store,
		agentDir,
		sessionDir,
		providerExtensionLoadout: {},
		modelRuntimeFactory: ({ sourceId }) => makeRuntime(agentDir, sourceId, respond),
	});
	t.after(async () => runner.close());
	return { root, agentDir, sessionDir, cwd, store, runner };
}

function makeBatch(sourceId, cwd, evidenceId, options = {}) {
	return {
		sourceId,
		cwd,
		batchId: `batch-${evidenceId}`,
		pendingBatchIds: [`pending-${evidenceId}`],
		payload: {
			source: { id: sourceId, label: `Source ${sourceId}` },
			evidence: [{
				id: evidenceId,
				summary: `Observed workflow evidence ${evidenceId}.`,
				outcome: "completed",
				provenance: { pointer: `test://${sourceId}/${evidenceId}`, availability: "available" },
			}],
		},
		explicit: false,
		focus: null,
		modelOverride: null,
		primaryModel: { provider: "scripted", id: "reviewer-a" },
		...options,
	};
}

function lastUserText(content) {
	return typeof content === "string" ? content : Array.isArray(content) ? content.map((item) => item?.text ?? "").join("\n") : "";
}

async function createPrimarySession({ cwd, agentDir, sessionDir, runtime }) {
	const manager = sdk.SessionManager.create(cwd, sessionDir);
	const settingsManager = sdk.SettingsManager.inMemory({ cacheWarming: "off" });
	const resourceLoader = new sdk.DefaultResourceLoader({
		cwd,
		agentDir,
		settingsManager,
		noExtensions: true,
		noSkills: true,
		noPromptTemplates: true,
		noThemes: true,
		noContextFiles: true,
		systemPrompt: "You are the primary scripted test session.",
	});
	await resourceLoader.reload();
	const { session } = await sdk.createAgentSession({
		cwd,
		agentDir,
		sessionManager: manager,
		settingsManager,
		resourceLoader,
		modelRuntime: runtime,
		model: runtime.getModel("scripted", "reviewer-a"),
		tools: [],
	});
	return session;
}

test("default provider-extension loadout matches Pi's installed package paths", () => {
	const agentDir = path.join(os.tmpdir(), "pi-agent");
	assert.deepEqual(getDefaultProviderExtensionLoadout(agentDir), {
		"claude-compat": [path.join(agentDir, "extensions/claude-compat-guard/index.ts")],
		cursor: [path.join(agentDir, "git/github.com/cartwmic/pi-cursor/src/index.ts")],
		openrouter: [path.join(agentDir, "git/github.com/olixis/pi-openrouter-plus/extensions/openrouter-routing/index.ts")],
	});
});

test("native observer sessions persist, resume, use only read/search tools, follow model switches, and stay out of capture", async (t) => {
	const calls = [];
	const active = new Map();
	const peak = new Map();
	const { cwd, agentDir, store, runner, sessionDir } = await fixture(t, async ({ sourceId, model, options, lastUser, context }) => {
		const key = sourceId ?? "primary";
		active.set(key, (active.get(key) ?? 0) + 1);
		peak.set(key, Math.max(peak.get(key) ?? 0, active.get(key)));
		await new Promise((resolve) => setTimeout(resolve, 5));
		calls.push({ sourceId, model: model.id, prompt: lastUserText(lastUser) });
		try {
			const prompt = lastUserText(lastUser);
			if (prompt.includes('"id": "evidence-read"') && !context.messages.some((message) => message.role === "toolResult")) {
				return { kind: "tool", name: "read", arguments: { path: path.join(cwd, "relevant.txt") } };
			}
			return { kind: "text", text: JSON.stringify({ proposals: [], model: model.id }) };
		} finally {
			active.set(key, active.get(key) - 1);
		}
	});
	const filename = path.join(cwd, "relevant.txt");
	await fs.writeFile(filename, "The scripted provider can read this relevant file.", "utf8");
	const sourceA = "pi-source-primary-a";
	const sourceB = "pi-source-primary-b";

	const first = await runner.run(makeBatch(sourceA, cwd, "evidence-read", { focus: "Review reusable verification opportunities" }));
	assert.match(first.text, /proposals/);
	assert.equal(first.model.id, "reviewer-a");
	assert.ok(first.sessionFile);
	assert.ok((await fs.stat(first.sessionFile)).isFile());
	assert.match(calls[0].prompt, /Serialized activity batch/);
	assert.match(calls[0].prompt, /non-obvious, evidence-backed failure mode or decision rule/);
	assert.match(calls[0].prompt, /asking for color in a monochrome terminal mock-up does not establish a process lesson/);
	assert.match(calls[0].prompt, /stateful command fails after a session switch/);
	assert.match(calls[0].prompt, /Return at most two strong proposals; zero is normal/);
	assert.match(calls[0].prompt, /evidence-read/);
	assert.match(calls[0].prompt, /Review reusable verification opportunities/);
	const workerStats = await runner.stats(sourceA);
	assert.ok(workerStats.tools.includes("read"));
	assert.ok(workerStats.tools.every((name) => ["read", "grep", "find", "ls"].includes(name)));
	assert.ok(workerStats.nativeStats.cost > 0);

	const parallelResults = await Promise.all([
		runner.run(makeBatch(sourceA, cwd, "evidence-switch-b", { primaryModel: { provider: "scripted", id: "reviewer-b" } })),
		runner.run(makeBatch(sourceA, cwd, "evidence-override-a", {
			primaryModel: { provider: "scripted", id: "reviewer-b" },
			modelOverride: "scripted/reviewer-a",
		})),
	]);
	assert.deepEqual(parallelResults.map((result) => result.model.id), ["reviewer-b", "reviewer-a"]);
	assert.equal(peak.get(sourceA), 1, "batches for one primary must execute serially");

	const otherPrimary = await runner.run(makeBatch(sourceB, cwd, "evidence-distinct"));
	assert.notEqual(otherPrimary.sessionFile, first.sessionFile);
	assert.equal(otherPrimary.model.id, "reviewer-a");
	assert.ok(calls.some((call) => call.model === "reviewer-b"));

	const stateA = await store.getOperationalState(sourceA);
	const stateB = await store.getOperationalState(sourceB);
	assert.equal(stateA.workerSession, first.sessionFile);
	assert.equal(stateB.workerSession, otherPrimary.sessionFile);

	await runner.close();
	const resumedRunner = createPiObserverRunner({
		sdk,
		store,
		agentDir,
		sessionDir,
		providerExtensionLoadout: {},
		modelRuntimeFactory: ({ sourceId }) => makeRuntime(agentDir, sourceId, async ({ model }) => ({ kind: "text", text: `resumed on ${model.id}` })),
	});
	t.after(async () => resumedRunner.close());
	const resumed = await resumedRunner.resume(sourceA, { cwd });
	assert.equal(resumed.ok, true);
	assert.equal(resumed.sessionFile, first.sessionFile);
	assert.equal(resumed.model.id, "reviewer-a");
	assert.ok(resumed.nativeStats.cost > 0);
	const later = await resumedRunner.run(makeBatch(sourceA, cwd, "evidence-after-resume", {
		primaryModel: { provider: "scripted", id: "reviewer-b" },
	}));
	assert.equal(later.sessionFile, first.sessionFile);
	assert.equal(later.model.id, "reviewer-b");
	assert.ok(later.nativeStats.cost >= resumed.nativeStats.cost);

	const piSession = sdk.SessionManager.open(first.sessionFile, sessionDir);
	assert.equal(isObserverSession(piSession), true);
	assert.ok(piSession.getSessionName?.()?.startsWith("Learnings observer"));
	const savedLines = (await fs.readFile(first.sessionFile, "utf8")).trim().split("\n").map((line) => JSON.parse(line));
	assert.ok(savedLines.some((entry) => entry.type === "custom" && entry.customType === OBSERVER_SESSION_MARKER));
	assert.ok(savedLines.some((entry) => entry.type === "session_info" && entry.name.startsWith("Learnings observer")));
	assert.ok(savedLines.some((entry) => entry.type === "message" && entry.message.role === "toolResult" && entry.message.toolName === "read" && JSON.stringify(entry.message.content).includes("relevant file")));
	assert.ok(savedLines.some((entry) => entry.type === "message" && entry.message.role === "assistant" && entry.message.usage?.cost?.total > 0));

	const capture = createPiCaptureBridge({ store });
	const ignored = await capture.status({ cwd, sessionManager: piSession, model: { provider: "scripted", id: "reviewer-b" } });
	assert.deepEqual(ignored, { ok: false, reason: "observer" });
});

test("observer waits for durable session association before model work", async (t) => {
	const root = await fs.mkdtemp(path.join(os.tmpdir(), "learnings-observer-delayed-association-"));
	t.after(async () => fs.rm(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 10 }));
	const agentDir = path.join(root, "agent");
	const sessionDir = path.join(root, "sessions");
	const cwd = path.join(root, "workspace");
	await Promise.all([
		fs.mkdir(agentDir, { recursive: true }),
		fs.mkdir(sessionDir, { recursive: true }),
		fs.mkdir(cwd, { recursive: true }),
	]);
	const backingStore = createLearningStore({ root: path.join(root, "local-store") });
	let startAssociation;
	let releaseAssociation;
	let modelStarted = false;
	const associationStarted = new Promise((resolve) => { startAssociation = resolve; });
	const associationGate = new Promise((resolve) => { releaseAssociation = resolve; });
	const store = {
		getOperationalState: (...args) => backingStore.getOperationalState(...args),
		updateOperationalState: (sourceId, patch) => {
			if (Object.hasOwn(patch, "workerSession")) {
				startAssociation();
				return associationGate.then(() => backingStore.updateOperationalState(sourceId, patch));
			}
			return backingStore.updateOperationalState(sourceId, patch);
		},
	};
	const sourceId = "pi-source-delayed-association";
	const runner = createPiObserverRunner({
		sdk,
		store,
		agentDir,
		sessionDir,
		providerExtensionLoadout: {},
		modelRuntimeFactory: ({ sourceId: id }) => makeRuntime(agentDir, id, async () => {
			modelStarted = true;
			return { kind: "text", text: JSON.stringify({ proposals: [] }) };
		}),
	});
	t.after(async () => {
		releaseAssociation();
		await runner.close();
	});

	const pending = runner.run(makeBatch(sourceId, cwd, "delayed-association"));
	await associationStarted;
	assert.equal(modelStarted, false);
	assert.equal((await backingStore.getOperationalState(sourceId)).workerSession, null);

	releaseAssociation();
	const result = await pending;
	assert.equal(modelStarted, true);
	assert.match(result.text, /proposals/);
	assert.ok(result.nativeStats.cost > 0);
	assert.ok((await fs.stat(result.sessionFile)).isFile());
	assert.equal((await backingStore.getOperationalState(sourceId)).workerSession, result.sessionFile);
});

test("native observer stats do not queue behind a held model response", async (t) => {
	let release;
	let entered;
	const held = new Promise((resolve) => { release = resolve; });
	const started = new Promise((resolve) => { entered = resolve; });
	const { runner, cwd, store } = await fixture(t, async () => { entered(); return held; });
	const sourceId = "pi-source-held-stats";
	const pending = runner.run(makeBatch(sourceId, cwd, "held-model"));
	try {
		await started;
		const state = await store.getOperationalState(sourceId);
		assert.ok(state.workerSession);
		const stats = await Promise.race([
			runner.stats(sourceId),
			new Promise((_, reject) => setTimeout(() => reject(new Error("stats waited on the held observer")), 150)),
		]);
		assert.equal(stats.running, true);
		assert.equal(stats.sessionFile, state.workerSession);
		assert.equal(stats.available, true);
		assert.ok(stats.nativeStats);
	} finally {
		release({ kind: "text", text: JSON.stringify({ proposals: [] }) });
		await pending;
	}
});

test("the native OpenAI-compatible stream completes a read tool round-trip before returning proposals", async (t) => {
	const root = await fs.mkdtemp(path.join(os.tmpdir(), "learnings-observer-openai-stream-"));
	t.after(async () => fs.rm(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 10 }));
	const agentDir = path.join(root, "agent");
	const sessionDir = path.join(root, "sessions");
	const cwd = path.join(root, "workspace");
	const filename = path.join(cwd, "relevant.txt");
	await Promise.all([
		fs.mkdir(agentDir, { recursive: true }),
		fs.mkdir(sessionDir, { recursive: true }),
		fs.mkdir(cwd, { recursive: true }),
	]);
	await fs.writeFile(filename, "Relevant content from the scripted local provider.", "utf8");
	const requests = [];
	const server = createServer(async (req, res) => {
		let body = "";
		for await (const chunk of req) body += chunk;
		const request = JSON.parse(body);
		requests.push(request);
		const common = {
			id: `chatcmpl-scripted-${requests.length}`,
			object: "chat.completion.chunk",
			created: 1,
			model: "dummy-model",
		};
		const chunks = requests.length === 1
			? [
				{ choices: [{ index: 0, delta: { role: "assistant" }, finish_reason: null }] },
				{ choices: [{ index: 0, delta: { tool_calls: [{
					index: 0,
					id: "scripted-read-call",
					type: "function",
					function: { name: "read", arguments: JSON.stringify({ path: filename }) },
				}] }, finish_reason: null }] },
				{ choices: [{ index: 0, delta: {}, finish_reason: "tool_calls" }] },
			]
			: [
				{ choices: [{ index: 0, delta: { role: "assistant" }, finish_reason: null }] },
				{ choices: [{ index: 0, delta: { content: JSON.stringify({ proposals: [] }) }, finish_reason: null }] },
				{ choices: [{ index: 0, delta: {}, finish_reason: "stop" }] },
			];
		res.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache", connection: "keep-alive" });
		for (const chunk of [...chunks, { choices: [], usage: { prompt_tokens: 30, completion_tokens: 12, total_tokens: 42 } }]) {
			res.write(`data: ${JSON.stringify({ ...common, ...chunk })}\n\n`);
		}
		res.end("data: [DONE]\n\n");
	});
	await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
	t.after(async () => new Promise((resolve) => server.close(resolve)));
	const address = server.address();
	assert.ok(address && typeof address === "object");
	const modelsPath = path.join(agentDir, "models.json");
	await fs.writeFile(modelsPath, JSON.stringify({
		providers: {
			openai: {
				baseUrl: `http://127.0.0.1:${address.port}/v1`,
				api: "openai-completions",
				apiKey: "scripted-local-key",
				models: [{
					id: "dummy-model",
					name: "Scripted local model",
					reasoning: false,
					input: ["text"],
					cost: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0 },
					contextWindow: 32_000,
					maxTokens: 2_000,
				}],
			},
		},
	}), "utf8");
	const store = createLearningStore({ root: path.join(root, "local-store") });
	const runner = createPiObserverRunner({
		sdk,
		store,
		agentDir,
		sessionDir,
		providerExtensionLoadout: {},
	});
	const sourceId = "pi-source-openai-stream-round-trip";
	t.after(async () => runner.close());
	let timeout;
	let result;
	const runPromise = runner.run(makeBatch(sourceId, cwd, "openai-stream-read", {
		primaryModel: { provider: "openai", id: "dummy-model" },
	}));
	try {
		result = await Promise.race([
			runPromise,
			new Promise((_, reject) => { timeout = setTimeout(() => reject(new Error("native streamed tool round-trip did not settle")), 5_000); }),
		]);
	} catch (error) {
		await runner.abort(sourceId).catch(() => {});
		throw error;
	} finally {
		clearTimeout(timeout);
	}

	assert.equal(requests.length, 2, "the observer must request a final response after the read result");
	assert.equal(requests[1].messages.at(-1).role, "tool");
	assert.deepEqual(result.text, JSON.stringify({ proposals: [] }));
	assert.ok(result.sessionFile);
	const entries = (await fs.readFile(result.sessionFile, "utf8")).trim().split("\n").map((line) => JSON.parse(line));
	const messages = entries.filter((entry) => entry.type === "message").map((entry) => entry.message);
	assert.ok(messages.some((message) => message.role === "toolResult" && message.toolName === "read"));
	assert.equal(messages.filter((message) => message.role === "assistant").at(-1).stopReason, "stop");
	assert.ok(result.nativeStats.tokens.total > 0);
	assert.ok(result.nativeStats.cost > 0);
});

test("aborting an observer leaves durable activity pending and does not abort the primary session", async (t) => {
	let signalPrimary;
	let signalObserver;
	let observerStartedResolve;
	const observerStarted = new Promise((resolve) => { observerStartedResolve = resolve; });
	let firstObserverRequest = true;
	const { cwd, agentDir, sessionDir, store, runner } = await fixture(t, async ({ options, lastUser }) => {
		const prompt = lastUserText(lastUser);
		if (prompt.includes("primary work should continue")) {
			signalPrimary = options.signal;
			await new Promise((resolve) => setTimeout(resolve, 150));
			return { kind: "text", text: "Primary completed normally." };
		}
		if (prompt.includes("Serialized activity batch") && firstObserverRequest) {
			firstObserverRequest = false;
			signalObserver = options.signal;
			observerStartedResolve();
			return new Promise((resolve) => {
				if (options.signal?.aborted) return resolve({ kind: "aborted" });
				options.signal?.addEventListener("abort", () => resolve({ kind: "aborted" }), { once: true });
			});
		}
		return { kind: "text", text: JSON.stringify({ proposals: [] }) };
	});
	const primaryRuntime = await makeRuntime(agentDir, "primary", async ({ options, lastUser }) => {
		signalPrimary = options.signal;
		await new Promise((resolve) => setTimeout(resolve, 150));
		return { kind: "text", text: "Primary completed normally." };
	});
	const primary = await createPrimarySession({ cwd, agentDir, sessionDir: path.join(sessionDir, "primary"), runtime: primaryRuntime });
	const sourceId = piSourceId(primary.sessionId);
	await store.updateOperationalState(sourceId, { enabled: true });
	const activity = {
		source: { id: sourceId, label: "Scripted primary" },
		evidence: [{ id: "cancel-evidence", summary: "A captured batch must remain pending after cancellation.", outcome: "completed", provenance: { pointer: "test://cancel-evidence", availability: "available" } }],
	};
	await store.enqueuePending(sourceId, { id: "pending-cancel-evidence", payload: activity, cursorAfter: { last: "cancel-evidence" } });
	const scheduled = [];
	const capture = createPiCaptureBridge({
		store,
		batchThreshold: 3,
		scheduleBatch: async (batch) => {
			const run = runner.run(batch);
			scheduled.push(run);
			const result = await run;
			const records = await store.readRecords(sourceId);
			const parsed = JSON.parse(result.text);
			const review = reviewActivity({ activity: batch.payload, proposals: parsed.proposals, records });
			await store.applyChanges(sourceId, review.changes, { basedOn: records });
			return result;
		},
		cancelWorker: (id) => runner.abort(id),
	});
	const context = { cwd, sessionManager: primary.sessionManager, model: { provider: "scripted", id: "reviewer-a" } };

	const primaryPrompt = primary.prompt("primary work should continue while the observer is cancelled.");
	const flush = await capture.flush(context);
	assert.equal(flush.scheduled, true);
	await observerStarted;
	assert.equal(primary.isStreaming, true);
	assert.ok(signalPrimary && !signalPrimary.aborted);
	assert.ok(signalObserver);

	await runner.abort(sourceId);
	await assert.rejects(scheduled[0], (error) => error.code === "aborted");
	assert.equal(signalObserver.aborted, true);
	assert.equal(signalPrimary.aborted, false);
	assert.equal(primary.isStreaming, true);
	assert.equal((await store.getOperationalState(sourceId)).pending.length, 1);
	await primaryPrompt;
	assert.equal([...primary.messages].reverse().find((message) => message.role === "assistant")?.stopReason, "stop");

	await capture.flush(context);
	for (let tries = 0; tries < 200 && (await store.getOperationalState(sourceId)).pending.length; tries++) {
		await new Promise((resolve) => setTimeout(resolve, 5));
	}
	assert.equal((await store.getOperationalState(sourceId)).pending.length, 0, "retry should finish the durable batch");
	assert.ok(scheduled.length >= 2);
	primary.dispose();
});

test("aborting during model selection does not start a late observer prompt", async (t) => {
	const root = await fs.mkdtemp(path.join(os.tmpdir(), "learnings-observer-select-cancel-"));
	t.after(async () => fs.rm(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 10 }));
	const agentDir = path.join(root, "agent");
	const sessionDir = path.join(root, "sessions");
	const cwd = path.join(root, "workspace");
	await Promise.all([
		fs.mkdir(agentDir, { recursive: true }),
		fs.mkdir(sessionDir, { recursive: true }),
		fs.mkdir(cwd, { recursive: true }),
	]);
	let authGateEnabled = false;
	let releaseAuth;
	let signalAuthStarted;
	const authGate = new Promise((resolve) => { releaseAuth = resolve; });
	const authStarted = new Promise((resolve) => { signalAuthStarted = resolve; });
	let requests = 0;
	const store = createLearningStore({ root: path.join(root, "local-store") });
	const runner = createPiObserverRunner({
		sdk,
		store,
		agentDir,
		sessionDir,
		providerExtensionLoadout: {},
		modelRuntimeFactory: async ({ sourceId }) => {
			const runtime = await makeRuntime(agentDir, sourceId, async () => {
				requests++;
				return { kind: "text", text: JSON.stringify({ proposals: [] }) };
			});
			const checkAuth = runtime.checkAuth.bind(runtime);
			runtime.checkAuth = async (provider) => {
				if (authGateEnabled) {
					authGateEnabled = false;
					signalAuthStarted();
					await authGate;
				}
				return checkAuth(provider);
			};
			return runtime;
		},
	});
	t.after(async () => runner.close());
	const sourceId = "pi-source-select-cancel";
	await runner.run(makeBatch(sourceId, cwd, "select-cancel-first"));
	authGateEnabled = true;
	const pending = runner.run(makeBatch(sourceId, cwd, "select-cancel-second", {
		primaryModel: { provider: "scripted", id: "reviewer-b" },
	}));
	await authStarted;
	const aborted = await runner.abort(sourceId);
	assert.equal(aborted.aborted, true);
	assert.equal(aborted.running, false);
	releaseAuth();
	await assert.rejects(pending, (error) => error.code === "aborted");
	assert.equal(requests, 1, "cancellation before prompt must not issue a provider request");
});

test("provider extension loadout supplies the selected route without loading the monitor extension", async (t) => {
	const root = await fs.mkdtemp(path.join(os.tmpdir(), "learnings-observer-provider-"));
	const agentDir = path.join(root, "agent");
	const sessionDir = path.join(root, "sessions");
	const cwd = path.join(root, "workspace");
	const providerPath = path.join(agentDir, "provider", "index.mjs");
	const secondProviderPath = path.join(agentDir, "second-provider", "index.mjs");
	await Promise.all([
		fs.mkdir(path.dirname(providerPath), { recursive: true }),
		fs.mkdir(path.dirname(secondProviderPath), { recursive: true }),
		fs.mkdir(path.join(agentDir, "extensions", "learnings-monitor"), { recursive: true }),
		fs.mkdir(sessionDir, { recursive: true }),
		fs.mkdir(cwd, { recursive: true }),
	]);
	const providerExtension = (provider, modelId) => `export default function (pi) {
	pi.registerProvider(${JSON.stringify(provider)}, {
		name: "Scripted extension provider",
		api: "openai-completions",
		baseUrl: "http://scripted.test/v1",
		apiKey: "scripted-test-key",
		models: [{ id: ${JSON.stringify(modelId)}, name: "Observer model", reasoning: false, input: ["text"], cost: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0 }, contextWindow: 32000, maxTokens: 2000 }],
		streamSimple: (model, context, options) => globalThis.__learningsObserverTestStream(model, context, options),
	});
}`;
	await Promise.all([
		fs.writeFile(providerPath, providerExtension("extension-scripted", "observer-model"), "utf8"),
		fs.writeFile(secondProviderPath, providerExtension("extension-scripted-b", "observer-model-b"), "utf8"),
		fs.writeFile(path.join(agentDir, "extensions", "learnings-monitor", "index.mjs"), "globalThis.__learningsObserverMonitorLoaded = true; export default () => {};", "utf8"),
	]);
	globalThis.__learningsObserverMonitorLoaded = false;
	globalThis.__learningsObserverTestStream = (model, _context, options) => scriptedStream(model, options, () => ({
		kind: "text",
		text: JSON.stringify({ proposals: [], route: `${model.provider}/${model.id}` }),
	}));
	const store = createLearningStore({ root: path.join(root, "local-store") });
	const runner = createPiObserverRunner({
		sdk,
		store,
		agentDir,
		sessionDir,
		providerExtensionLoadout: {
			"extension-scripted": [providerPath],
			"extension-scripted-b": [secondProviderPath],
		},
		modelRuntimeFactory: () => sdk.ModelRuntime.create({
			authPath: path.join(agentDir, "missing-auth.json"),
			modelsPath: null,
			allowModelNetwork: false,
			refreshOnCreate: false,
		}),
	});
	const sourceId = "pi-source-extension-route";
	try {
		const result = await runner.run(makeBatch(sourceId, cwd, "extension-route", {
			primaryModel: { provider: "extension-scripted", id: "observer-model" },
		}));
		assert.equal(result.model.provider, "extension-scripted");
		assert.match(result.text, /extension-scripted\/observer-model/);
		assert.equal(globalThis.__learningsObserverMonitorLoaded, false);
		assert.deepEqual((await runner.stats(sourceId)).providerExtensions, [providerPath]);
		const switched = await runner.run(makeBatch(sourceId, cwd, "extension-route-switch", {
			primaryModel: { provider: "extension-scripted-b", id: "observer-model-b" },
		}));
		assert.equal(switched.model.provider, "extension-scripted-b");
		assert.equal(switched.sessionFile, result.sessionFile, "provider switches must resume the same observer session");
		assert.deepEqual((await runner.stats(sourceId)).providerExtensions, [secondProviderPath]);
	} finally {
		await runner.close();
		delete globalThis.__learningsObserverTestStream;
		delete globalThis.__learningsObserverMonitorLoaded;
		await fs.rm(root, { recursive: true, force: true });
	}
});

test("Compat observer binds session-start guard before its real SDK prompt", async (t) => {
	const root = await fs.mkdtemp(path.join(os.tmpdir(), "learnings-compat-guard-"));
	const agentDir = path.join(root, "agent"), cwd = path.join(root, "work"), sessionDir = path.join(root, "sessions");
	const providerPath = path.join(agentDir, "provider.mjs");
	const guardModule = pathToFileURL(path.resolve(import.meta.dirname, "../claude-compat-guard/guard.mjs")).href;
	await Promise.all([agentDir, cwd, sessionDir].map(p => fs.mkdir(p, { recursive: true })));
	await fs.writeFile(path.join(agentDir, "auth.json"), JSON.stringify({ "claude-compat": { type: "api_key", key: "scripted-test-key" } }));
	const docs = "<docs>\nPi documentation (read only when the user asks about pi itself, its SDK):\n- Topics: models (docs/models.md), pi packages (docs/packages.md), MCP\n</docs>";
	await fs.writeFile(providerPath, `import { guardProvider } from ${JSON.stringify(guardModule)};
export default function(pi) {
	let started = false;
	pi.on("session_start", () => { started = true; });
	const stream = (model, context, options) => globalThis.__learningsCompatGuardStream(model, context, options, started);
	const provider = {
		id: "claude-compat", name: "Scripted Compat", baseUrl: "http://scripted.test/v1",
		auth: { apiKey: { name: "Scripted key", resolve: async ({ credential }) => credential?.key
			? { auth: { apiKey: credential.key }, source: "stored credential" } : undefined } },
		getModels: () => [{ id: "compat-observer", name: "Compat observer", provider: "claude-compat",
			api: "claude-compat-messages", baseUrl: "http://scripted.test/v1", input: ["text"],
			reasoning: false, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
			contextWindow: 32000, maxTokens: 2000 }],
		stream, streamSimple: stream,
	};
	pi.registerProvider(guardProvider(provider));
	pi.on("before_agent_start", (event, ctx) => {
		globalThis.__learningsCompatGuardInstalled = ctx.modelRegistry.getRegisteredNativeProvider("claude-compat").streamSimple !== stream;
		return { systemPromptOptions: { ...event.systemPromptOptions,
			sections: { ...event.systemPromptOptions.sections, docs: ${JSON.stringify(docs)} } } };
	});
}`);
	let calls = 0;
	globalThis.__learningsCompatGuardStream = (model, context, options, started) => scriptedStream(model, options, () => {
		assert.equal(started, true, "upstream session_start must run");
		assert.equal(globalThis.__learningsCompatGuardInstalled, true, "session_start must run before observer prompt");
		const transmitted = context.messages.filter(m => m.role === "system").map(m => m.sections?.docs ?? m.content).join("\\n");
		assert.match(transmitted, /about Pi itself/);
		assert.match(transmitted, /, Pi packages \(docs\/packages.md\),/);
		assert.doesNotMatch(transmitted, /about pi itself/);
		calls++;
		return { kind: "text", text: '{"proposals":[]}' };
	});
	const runner = createPiObserverRunner({
		sdk, agentDir, cwd, sessionDir,
		store: createLearningStore({ root: path.join(root, "store") }),
		providerExtensionLoadout: { "claude-compat": [providerPath] },
		resourceLoaderFactory: ({ cwd, agentDir, settingsManager, extensionPaths }) => {
			const loader = new sdk.DefaultResourceLoader({ cwd, agentDir, settingsManager,
				additionalExtensionPaths: extensionPaths, noExtensions: true, noSkills: true,
				noPromptTemplates: true, noThemes: true, noContextFiles: true });
			const reload = loader.reload.bind(loader);
			loader.reload = async () => { await reload(); assert.deepEqual(loader.getExtensions().errors, []); };
			return loader;
		},
	});
	try {
		const result = await runner.run(makeBatch("compat-guard-source", cwd, "compat-evidence", {
			primaryModel: { provider: "claude-compat", id: "compat-observer" },
		}));
		assert.deepEqual(JSON.parse(result.text), { proposals: [] });
		assert.equal(calls, 1);
		const saved = await fs.readFile(result.sessionFile, "utf8");
		assert.match(saved, /about pi itself/);
		assert.doesNotMatch(saved, /about Pi itself/);
	} finally {
		await runner.close();
		delete globalThis.__learningsCompatGuardStream;
		delete globalThis.__learningsCompatGuardInstalled;
		await fs.rm(root, { recursive: true, force: true });
	}
});

test("an unavailable selected provider fails closed and leaves the capture batch pending", async (t) => {
	const { cwd, sessionDir, store, runner } = await fixture(t, async () => ({ kind: "text", text: "must not be used as a fallback" }));
	const primaryManager = sdk.SessionManager.create(cwd, path.join(sessionDir, "primary"));
	const sourceId = piSourceId(primaryManager.getSessionId());
	await store.updateOperationalState(sourceId, { enabled: true });
	await store.enqueuePending(sourceId, {
		id: "pending-unavailable-model",
		payload: {
			source: { id: sourceId, label: "Unavailable primary model" },
			evidence: [{ id: "unavailable-evidence", summary: "Keep this while the selected provider is unavailable.", outcome: "completed", provenance: { pointer: "test://unavailable", availability: "available" } }],
		},
	});
	let rejectError;
	let failedResolve;
	const failed = new Promise((resolve) => { failedResolve = resolve; });
	const bridge = createPiCaptureBridge({
		store,
		scheduleBatch: (batch) => runner.run(batch),
		onError: (error) => { rejectError = error; failedResolve(error); },
	});
	await bridge.flush({ cwd, sessionManager: primaryManager, model: { provider: "not-loaded", id: "unavailable" } });
	await failed;
	assert.equal(rejectError.code, "model-unavailable");
	assert.ok(rejectError.sessionFile);
	const state = await store.getOperationalState(sourceId);
	assert.equal(state.pending.length, 1);
	assert.equal(state.workerSession, rejectError.sessionFile);
});

test("observer tools reject shell and mutation capabilities at configuration time", async () => {
	assert.throws(() => createPiObserverRunner({ sdk, store: createLearningStore({ root: os.tmpdir() }), tools: ["read", "bash"] }), /not read-only/);
});
