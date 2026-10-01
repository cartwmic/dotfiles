import assert from "node:assert/strict";
import fs from "node:fs/promises";
import { existsSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import { createLearningStore } from "./store.mjs";
import { piSourceId } from "./capture.mjs";
import { createLearningsMonitorRuntime } from "./runtime.mjs";
import { createLearningsMonitorControls } from "./control.mjs";

class ScriptedSession {
	constructor(id, persisted = true) {
		this.id = id;
		this.persisted = persisted;
		this.entries = [];
		this.leaf = null;
		this.clock = Date.now();
	}
	getSessionId() { return this.id; }
	getSessionFile() { return this.persisted ? `/private/pi/${this.id}.jsonl` : undefined; }
	isPersisted() { return this.persisted; }
	getEntries() { return [...this.entries]; }
	getLeafId() { return this.leaf; }
	getBranch() {
		const byId = new Map(this.entries.map((entry) => [entry.id, entry]));
		const result = [];
		let current = byId.get(this.leaf);
		while (current) {
			result.push(current);
			current = current.parentId ? byId.get(current.parentId) : undefined;
		}
		return result.reverse();
	}
	add(role, content, extra = {}) {
		const id = `entry-${this.entries.length + 1}`;
		const timestamp = this.clock = Math.max(this.clock + 1, Date.now() + 1);
		const entry = {
			id,
			parentId: this.leaf,
			timestamp: new Date(timestamp).toISOString(),
			type: "message",
			message: { role, content, timestamp, ...extra },
		};
		this.entries.push(entry);
		this.leaf = id;
		return entry;
	}
}

function addExchange(session, label = "request") {
	session.add("user", `Please investigate ${label}.`);
	session.add("assistant", [{ type: "text", text: `I completed ${label}.` }], { stopReason: "stop" });
}

function makePi() {
	const commands = new Map();
	const handlers = new Map();
	return {
		commands,
		handlers,
		registerCommand(name, options) { commands.set(name, options.handler); },
		on(event, handler) {
			const listeners = handlers.get(event) ?? [];
			listeners.push(handler);
			handlers.set(event, listeners);
		},
		async emit(event, payload, ctx) {
			for (const listener of handlers.get(event) ?? []) await listener(payload, ctx);
		},
	};
}

async function invokeCommand(handler, args, ctx, notifications) {
	const previous = notifications.length;
	await handler(args, ctx);
	return notifications.slice(previous).find((item) => item.type !== "warning")?.message ?? "";
}

function makeContext(session, notifications, model = { provider: "scripted", id: "primary-v1" }) {
	const mutationAttempts = [];
	const ctx = {
		cwd: "/workspace/project",
		sessionManager: session,
		model,
		hasUI: true,
		mode: "tui",
		ui: {
			notify: (message, type) => notifications.push({ message, type }),
		},
		abort: () => mutationAttempts.push("abort"),
		sendMessage: () => mutationAttempts.push("sendMessage"),
		sendUserMessage: () => mutationAttempts.push("sendUserMessage"),
	};
	return { ctx, mutationAttempts };
}

async function fixture(t, options = {}) {
	const root = await fs.mkdtemp(path.join(os.tmpdir(), "learnings-controls-"));
	t.after(async () => fs.rm(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 10 }));
	const store = createLearningStore({ root: path.join(root, "store") });
	const pi = makePi();
	const runs = [];
	const aborts = [];
	const workerStates = new Map();
	let runCount = 0;
	const createWorker = (tools) => ({
		tools: [...tools],
		async run(batch) {
			runs.push({ ...batch, tools: [...tools] });
			const current = workerStates.get(batch.sourceId) ?? {
				sessionFile: path.join(root, `observer-${batch.sourceId}.jsonl`),
				sessionId: `observer-${batch.sourceId}`,
				model: null,
				running: false,
				lastError: null,
				cost: 0,
			};
			current.running = true;
			workerStates.set(batch.sourceId, current);
			await store.updateOperationalState(batch.sourceId, { workerSession: current.sessionFile });
			const ordinal = ++runCount;
			try {
				if (options.onRun) await options.onRun({ batch, ordinal, runner: this, current });
				current.model = batch.modelOverride
					? Object.fromEntries([["provider", batch.modelOverride.split("/")[0]], ["id", batch.modelOverride.slice(batch.modelOverride.indexOf("/") + 1)]])
					: batch.primaryModel;
				current.cost += 0.004;
				current.lastError = null;
				const proposal = options.proposalForBatch?.(batch) ?? {
					type: "improvement",
					observation: `Manual workflow step in ${batch.payload.evidence[0].id}.`,
					recommendation: "Consider a reusable helper for the repeated step.",
					evidenceIds: [batch.payload.evidence[0].id],
				};
				return {
					text: JSON.stringify({ proposals: [proposal] }),
					sessionFile: current.sessionFile,
					sessionId: current.sessionId,
					nativeStats: { tokens: { input: ordinal * 10, output: ordinal * 5, total: ordinal * 15 }, cost: current.cost },
				};
			} catch (error) {
				current.lastError = error.code === "aborted" ? null : error.message;
				throw error;
			} finally {
				current.running = false;
			}
		},
		async stats(sourceId) {
			const state = await store.getOperationalState(sourceId);
			const current = workerStates.get(sourceId);
			return {
				sourceId,
				observerSession: Boolean(current),
				sessionFile: current?.sessionFile ?? state.workerSession,
				sessionId: current?.sessionId ?? null,
				model: current?.model ?? null,
				running: current?.running ?? false,
				tools: [...tools],
				nativeStats: current ? {
					tokens: { input: 10, output: 5, total: 15 },
					cost: current.cost,
				} : null,
				lastError: current?.lastError ?? null,
				available: current || state.workerSession ? true : undefined,
				pending: state.pending.length,
			};
		},
		async abort(sourceId) {
			aborts.push(sourceId);
			return options.onAbort?.(sourceId, this);
		},
		async close() {},
	});
	const runtime = createLearningsMonitorRuntime(pi, {
		store,
		createWorker,
		memory: options.memory ?? null,
		batchThreshold: options.batchThreshold,
	});
	const notifications = [];
	return { root, store, pi, runtime, runs, aborts, notifications, makeContext, workerStates };
}

async function waitFor(predicate, message = "condition did not become true") {
	for (let attempt = 0; attempt < 200; attempt++) {
		if (await predicate()) return;
		await new Promise((resolve) => setTimeout(resolve, 5));
	}
	assert.fail(message);
}

function deferred() {
	let resolve;
	let reject;
	const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
	return { promise, resolve, reject };
}

test("/learnings controls opt in, cancel only the observer, preserve disabled pending work, flush, and leave primary context untouched", async (t) => {
	const held = deferred();
	const started = deferred();
	let firstRun = true;
	const fx = await fixture(t, {
		batchThreshold: 3,
		onRun: async ({ ordinal, runner }) => {
			if (firstRun) {
				firstRun = false;
				runner.active = held;
				started.resolve();
				return held.promise;
			}
			assert.ok(ordinal > 1);
		},
		onAbort: (sourceId, runner) => {
			if (runner.active) {
				runner.active.reject(Object.assign(new Error("observer cancelled"), { code: "aborted" }));
				runner.active = null;
			}
		},
	});
	const session = new ScriptedSession("primary-control-session");
	const { ctx, mutationAttempts } = makeContext(session, fx.notifications);
	const command = (args, ctx) => invokeCommand(fx.pi.commands.get("learnings"), args, ctx, fx.notifications);
	assert.equal(typeof fx.pi.commands.get("learnings"), "function");

	await fx.pi.emit("session_start", { reason: "resume" }, ctx);
	assert.match(await command("on", ctx), /monitor ON/);
	const sourceId = piSourceId(session.id);
	assert.equal((await fx.store.getOperationalState(sourceId)).enabled, true);

	addExchange(session, "below-threshold");
	await fx.pi.emit("agent_settled", {}, ctx);
	assert.equal((await fx.store.getOperationalState(sourceId)).pending.length, 1);
	assert.match(await command("flush", ctx), /flush queued/);
	await waitFor(() => fx.runs.length === 1, "flush did not start observer work");
	await started.promise;
	assert.match(await command("off", ctx), /monitor OFF/);
	assert.deepEqual(fx.aborts, [sourceId]);
	assert.equal((await fx.store.getOperationalState(sourceId)).pending.length, 1);

	await fx.pi.emit("session_start", { reason: "resume" }, ctx);
	await command("status", ctx);
	assert.equal(fx.notifications.filter((item) => item.type === "warning").length, 0, "an expected off cancellation is not a persistent failure");
	assert.equal(fx.runs.length, 1, "disabled resume must not run the observer");
	assert.equal((await fx.store.getOperationalState(sourceId)).enabled, false);
	assert.equal((await fx.store.getOperationalState(sourceId)).pending.length, 1);

	assert.match(await command("on", ctx), /monitor ON/);
	await waitFor(async () => (await fx.store.getOperationalState(sourceId)).pending.length === 0, "re-enable did not retry retained work");
	assert.equal(fx.runs.length, 2);
	assert.equal((await fx.store.readRecords(sourceId)).length, 1);

	await command("focus Automate the weekly report workflow", ctx);
	await command("model scripted/reviewer-v2", ctx);
	assert.match(await command("tools bash", ctx), /unsupported observer tool 'bash'/);
	await command("tools read,grep", ctx);
	assert.equal((await fx.store.getOperationalState(sourceId)).focus, "Automate the weekly report workflow");
	assert.equal((await fx.store.getOperationalState(sourceId)).modelOverride, "scripted/reviewer-v2");

	ctx.model = { provider: "scripted", id: "primary-v2" };
	addExchange(session, "explicit-flush");
	await fx.pi.emit("agent_settled", {}, ctx);
	assert.equal((await fx.store.getOperationalState(sourceId)).pending.length, 1);
	const status = await command("status", ctx);
	assert.match(status, /Observer session: .*observer-/);
	assert.match(status, /Pending: 1 batch/);
	assert.match(status, /cost \$0\.0040/);
	assert.match(status, /Model selection: override scripted\/reviewer-v2/);
	assert.match(status, /Observer tools: read, grep/);
	assert.match(await command("flush", ctx), /flush queued/);
	await waitFor(async () => (await fx.store.getOperationalState(sourceId)).pending.length === 0);
	assert.equal(fx.runs[2].focus, "Automate the weekly report workflow");
	assert.equal(fx.runs[2].modelOverride, "scripted/reviewer-v2");
	assert.deepEqual(fx.runs[2].tools, ["read", "grep"]);

	await command("model follow", ctx);
	addExchange(session, "follow-primary-model");
	await fx.pi.emit("agent_settled", {}, ctx);
	assert.match(await command("flush", ctx), /flush queued/);
	await waitFor(async () => (await fx.store.getOperationalState(sourceId)).pending.length === 0);
	assert.equal(fx.runs[3].modelOverride, null);
	assert.deepEqual(fx.runs[3].primaryModel, { provider: "scripted", id: "primary-v2" });
	assert.deepEqual(mutationAttempts, [], "controls must not abort or send messages in the primary session");
	assert.equal(session.getEntries().filter((entry) => entry.type === "message").length, 6);
	await fx.runtime.close();
});

test("ephemeral --no-session enable is refused and unsafe worker tools cannot be selected", async (t) => {
	let workerCreations = 0;
	const root = await fs.mkdtemp(path.join(os.tmpdir(), "learnings-ephemeral-"));
	t.after(() => fs.rm(root, { recursive: true, force: true }));
	const store = createLearningStore({ root });
	const pi = makePi();
	const runtime = createLearningsMonitorRuntime(pi, {
		store,
		createWorker: () => { workerCreations++; throw new Error("worker should not be created"); },
	});
	const session = new ScriptedSession("ephemeral-primary", false);
	const notifications = [];
	const { ctx, mutationAttempts } = makeContext(session, notifications);
	const command = (args, context) => invokeCommand(pi.commands.get("learnings"), args, context, notifications);
	assert.match(await command("on", ctx), /unsupported in pi --no-session/);
	assert.match(await command("tools bash", ctx), /unsupported in pi --no-session/);
	assert.equal(workerCreations, 0);
	assert.deepEqual(mutationAttempts, []);
	await runtime.close();
});

test("a persistent warning never awaits observer stats during agent_settled", async () => {
	const pi = makePi();
	const session = new ScriptedSession("held-observer-warning");
	const notifications = [];
	const { ctx } = makeContext(session, notifications);
	const sourceId = piSourceId(session.id);
	let statsCalls = 0;
	const state = { enabled: true, pending: [] };
	const controls = createLearningsMonitorControls({
		capture: { status: async () => ({ ok: true, sourceId, enabled: true, state }) },
		store: { getOperationalState: async () => state },
		getWorker: () => ({ stats: () => { statsCalls++; return new Promise(() => {}); } }),
	});
	controls.register(pi);
	controls.recordFailure(sourceId, "observer", new Error("persistent observer error"));
	await Promise.race([
		pi.emit("agent_settled", {}, ctx),
		new Promise((_, reject) => setTimeout(() => reject(new Error("warning hook waited on observer stats")), 150)),
	]);
	assert.equal(statsCalls, 0);
	assert.deepEqual(notifications, [{
		message: "Learnings monitor has a persistent failure. Run /learnings status for details.",
		type: "warning",
	}]);
	await pi.emit("agent_settled", {}, ctx);
	assert.equal(notifications.length, 1);
});

test("observer failure warns once and stays visible in status", async (t) => {
	const fx = await fixture(t, {
		batchThreshold: 1,
		onRun: async () => { throw Object.assign(new Error("scripted provider unavailable"), { code: "model-unavailable" }); },
	});
	const session = new ScriptedSession("primary-failure-session");
	const { ctx } = makeContext(session, fx.notifications);
	const command = (args, context) => invokeCommand(fx.pi.commands.get("learnings"), args, context, fx.notifications);
	await command("on", ctx);
	addExchange(session, "failed-observer");
	await fx.pi.emit("agent_settled", {}, ctx);
	await waitFor(() => fx.runs.length === 1);
	const sourceId = piSourceId(session.id);
	await waitFor(() => Boolean(fx.runtime.controls.failureFor(sourceId)));
	assert.equal((await fx.store.getOperationalState(sourceId)).pending.length, 1);
	const firstStatus = await command("status", ctx);
	assert.match(firstStatus, /scripted provider unavailable/);
	assert.equal(fx.notifications.filter((item) => item.type === "warning").length, 1);
	await command("status", ctx);
	assert.equal(fx.notifications.filter((item) => item.type === "warning").length, 1, "repeated status must not spam warnings");
	await fx.runtime.close();
});

test("related-memory failure is fail-open for local proposals and warns only once", async (t) => {
	const fx = await fixture(t, {
		batchThreshold: 1,
		memory: {
			async related() { return { status: "failed", evidence: [], error: { kind: "timeout" } }; },
		},
	});
	const session = new ScriptedSession("primary-memory-failure-session");
	const { ctx } = makeContext(session, fx.notifications);
	const command = (args, context) => invokeCommand(fx.pi.commands.get("learnings"), args, context, fx.notifications);
	await command("on", ctx);
	addExchange(session, "memory-lookup-failure");
	await fx.pi.emit("agent_settled", {}, ctx);
	const sourceId = piSourceId(session.id);
	await waitFor(async () => (await fx.store.getOperationalState(sourceId)).pending.length === 0);
	assert.equal((await fx.store.readRecords(sourceId)).length, 1);
	const status = await command("status", ctx);
	assert.match(status, /related-memory lookup failed \(timeout\)/);
	await command("status", ctx);
	assert.equal(fx.notifications.filter((item) => item.type === "warning").length, 1);
	await fx.runtime.close();
});

test("new evidence keeps a repeated proposal eligible for related-memory lookup", async (t) => {
	const lookups = [];
	const fx = await fixture(t, {
		batchThreshold: 1,
		proposalForBatch: (batch) => ({
			type: "improvement",
			observation: "The verification checklist is repeated manually.",
			recommendation: "Consider a reusable verification helper.",
			evidenceIds: batch.payload.evidence.map((item) => item.id),
		}),
		memory: {
			async related(query) {
				lookups.push(query);
				return { status: "empty", evidence: [] };
			},
		},
	});
	const session = new ScriptedSession("primary-repeated-candidate-session");
	const { ctx } = makeContext(session, fx.notifications);
	await fx.pi.commands.get("learnings")("on", ctx);

	for (const label of ["first-evidence", "new-evidence"]) {
		addExchange(session, label);
		await fx.pi.emit("agent_settled", {}, ctx);
		await waitFor(async () => (await fx.store.getOperationalState(piSourceId(session.id))).pending.length === 0);
	}

	const records = await fx.store.readRecords(piSourceId(session.id));
	assert.equal(lookups.length, 2, "a changed record with new evidence must still reach related-memory lookup");
	assert.equal(records.length, 1, "the repeated proposal should update its existing opportunity");
	assert.equal(records[0].evidence.length, 2, "the existing opportunity should retain both distinct source events");
	assert.equal(records[0].evidenceAssessment.claim, "recurring");
	await fx.runtime.close();
});

test("the installed Pi extension loader loads index.ts and registers controls without a provider call", async (t) => {
	const moduleRoots = [
		...(process.env.NODE_PATH ?? "").split(path.delimiter).filter(Boolean),
		path.resolve(path.dirname(process.execPath), "../lib/node_modules"),
	];
	const sdkPath = moduleRoots
		.map((root) => path.join(root, "@earendil-works/pi-coding-agent", "dist", "index.js"))
		.find(existsSync);
	assert.ok(sdkPath, "Pi SDK installation must be available to load the extension");
	const packageRoot = path.dirname(path.dirname(sdkPath));
	const loader = await import(pathToFileURL(path.join(packageRoot, "dist/core/extensions/loader.js")).href);
	const root = await fs.mkdtemp(path.join(os.tmpdir(), "learnings-extension-loader-"));
	t.after(() => fs.rm(root, { recursive: true, force: true }));
	const previousXdg = process.env.XDG_DATA_HOME;
	process.env.XDG_DATA_HOME = path.join(root, "xdg");
	try {
		const extensionPath = path.join(path.dirname(fileURLToPath(import.meta.url)), "index.ts");
		const loaded = await loader.loadExtensions([extensionPath], root);
		assert.deepEqual(loaded.errors, []);
		assert.equal(loaded.extensions.length, 1);
		const extension = loaded.extensions[0];
		assert.deepEqual([...extension.commands.keys()], ["learnings"]);
		assert.ok(extension.handlers.has("session_start"));
		assert.ok(extension.handlers.has("agent_settled"));
		const notifications = [];
		const session = new ScriptedSession("ephemeral-loader-session", false);
		const { ctx } = makeContext(session, notifications);
		await extension.commands.get("learnings").handler("on", ctx);
		assert.match(notifications[0].message, /unsupported in pi --no-session/);
		assert.equal((await fs.readdir(path.join(root, "xdg")).catch(() => [])).length, 0);
	} finally {
		if (previousXdg === undefined) delete process.env.XDG_DATA_HOME;
		else process.env.XDG_DATA_HOME = previousXdg;
	}
});

test("T7 review registration receives only the stable review surface", async (t) => {
	const root = await fs.mkdtemp(path.join(os.tmpdir(), "learnings-review-seam-"));
	t.after(() => fs.rm(root, { recursive: true, force: true }));
	const store = createLearningStore({ root });
	const pi = makePi();
	let registered;
	const runtime = createLearningsMonitorRuntime(pi, {
		store,
		createWorker: () => ({ run: async () => ({ text: "{\"proposals\":[]}" }), stats: async () => ({}), abort: async () => ({}), close: async () => {} }),
		registerReviewCommands: (api, surface) => { registered = { api, surface }; },
	});
	assert.equal(registered.api, pi);
	assert.deepEqual(Object.keys(registered.surface).sort(), ["controls", "disposeWorker", "memory", "sourceStatus", "store", "workerStats"]);
	assert.equal(registered.surface.controls, runtime.controls);
	assert.equal(pi.commands.has("learnings"), false);
	assert.equal(registered.surface.store, store);
	assert.equal(registered.surface.memory, null);
	await runtime.close();
});
