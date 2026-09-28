import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { createLearningStore } from "./store.mjs";
import {
	OBSERVER_SESSION_MARKER,
	createPiCaptureBridge,
	isObserverSession,
	piBranchContext,
	piSourceId,
	privacyFilter,
	registerPiCaptureLifecycle,
} from "./capture.mjs";

class ScriptedSession {
	constructor(id, { persisted = true, entries = [] } = {}) {
		this.id = id;
		this.persisted = persisted;
		this.entries = [...entries];
		this.leaf = this.entries.at(-1)?.id ?? null;
		this.clock = 1_000_000;
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
	branch(entryId) {
		assert.ok(this.entries.some((entry) => entry.id === entryId));
		this.leaf = entryId;
	}
	add(entry) {
		const id = entry.id ?? `e${this.entries.length + 1}`;
		const timestamp = ++this.clock;
		const full = {
			id,
			parentId: this.leaf,
			timestamp: new Date(timestamp).toISOString(),
			type: "message",
			message: { timestamp, ...entry.message },
		};
		this.entries.push(full);
		this.leaf = id;
		return full;
	}
	addCustom(customType, data = {}) {
		const id = `custom-${this.entries.length + 1}`;
		const entry = { id, parentId: this.leaf, timestamp: new Date(++this.clock).toISOString(), type: "custom", customType, data };
		this.entries.push(entry);
		this.leaf = id;
		return entry;
	}
}

function makeContext(sessionManager, model = { provider: "scripted", id: "primary-v1" }) {
	return { cwd: "/workspace/project", sessionManager, model };
}

function makePi() {
	const handlers = new Map();
	return {
		handlers,
		on(event, handler) { handlers.set(event, handler); },
	};
}

function addExchange(session, {
	user = "Please inspect this workflow.",
	assistant = "I inspected the workflow.",
	stopReason = "stop",
	toolError = false,
	toolOutput = "",
	assistantError,
} = {}) {
	const userEntry = session.add({ message: { role: "user", content: user } });
	if (toolError || toolOutput) {
		session.add({ message: {
			role: "assistant",
			content: [{ type: "toolCall", id: `call-${session.entries.length}`, name: "read", arguments: { path: "/Users/alice/private.txt", token: "never-copy-this" } }],
			stopReason: "toolUse",
		} });
		session.add({ message: {
			role: "toolResult",
			toolCallId: `call-${session.entries.length - 1}`,
			toolName: "read",
			isError: toolError,
			content: [{ type: "text", text: toolOutput }],
		} });
	}
	const assistantEntry = session.add({ message: {
		role: "assistant",
		content: [{ type: "text", text: assistant }],
		stopReason,
		...(assistantError ? { errorMessage: assistantError } : {}),
	} });
	return { userEntry, assistantEntry };
}

async function temporaryStore(t) {
	const root = await fs.mkdtemp(path.join(os.tmpdir(), "learnings-capture-"));
	t.after(async () => fs.rm(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 10 }));
	return createLearningStore({ root });
}

async function waitFor(predicate, message = "condition did not become true") {
	for (let i = 0; i < 100; i++) {
		if (await predicate()) return;
		await new Promise((resolve) => setTimeout(resolve, 5));
	}
	assert.fail(message);
}

function deferred() {
	let resolve;
	const promise = new Promise((yes) => { resolve = yes; });
	return { promise, resolve };
}

async function startCapture({ store, session, threshold = 3, scheduled = [], cancelled = [], scheduleBatch, cancelWorker, now = () => 1_000_000 }) {
	const bridge = createPiCaptureBridge({
		store,
		batchThreshold: threshold,
		now,
		scheduleBatch: scheduleBatch ?? (async (batch) => { scheduled.push(batch); }),
		cancelWorker: cancelWorker ?? (async (sourceId) => { cancelled.push(sourceId); }),
	});
	const pi = makePi();
	registerPiCaptureLifecycle(pi, bridge);
	const ctx = makeContext(session);
	await pi.handlers.get("session_start")({ reason: "startup" }, ctx);
	return { bridge, pi, ctx, scheduled, cancelled };
}

test("privacy filter removes common credentials and personal identifiers before truncation", () => {
	const filtered = privacyFilter("API_KEY=sk-12345678901234567890 /Users/alice/a.txt alice@example.com", 300);
	assert.doesNotMatch(filtered, /sk-123|\/Users\/alice|alice@example\.com/);
	assert.match(filtered, /\[redacted\]/);
	assert.match(filtered, /\[user\]/);
	assert.match(filtered, /\[email\]/);
	assert.equal(privacyFilter("abcdefghij", 5), "abcd…");
});

test("settled events persist bounded evidence, defer below threshold, and checkpoint only after durable scheduling", async (t) => {
	const store = await temporaryStore(t);
	const session = new ScriptedSession("primary-one");
	const { bridge, pi, ctx, scheduled } = await startCapture({ store, session, threshold: 2 });
	const enabled = await bridge.enable(ctx);
	assert.equal(enabled.ok, true);
	assert.match(enabled.sourceId, /^pi-source-[a-f0-9]+$/);

	addExchange(session, {
		user: "Please inspect API_KEY=sk-12345678901234567890.",
		assistant: "The read failed, so I will not claim the requested data was retrieved.",
		toolError: true,
		toolOutput: `Could not open /Users/alice/private.txt; API_KEY=super-secret ${"x".repeat(1000)}`,
		assistantError: "tool error: token=another-secret",
	});
	const first = await pi.handlers.get("agent_settled")({}, ctx);
	assert.equal(first.captured, true);
	assert.equal((await store.getOperationalState(enabled.sourceId)).pending.length, 1);
	assert.equal(scheduled.length, 0);
	assert.equal((await bridge.captureSettled(ctx)).reason, "already-seen");

	ctx.model = { provider: "scripted", id: "primary-v2" };
	addExchange(session, { user: "I am stopping here.", assistant: "This attempt did not finish.", stopReason: "aborted" });
	await pi.handlers.get("agent_settled")({}, ctx);
	await waitFor(() => scheduled.length === 1, "threshold did not schedule a batch");
	const sent = scheduled[0].payload;
	assert.equal(sent.source.id, enabled.sourceId);
	assert.deepEqual(scheduled[0].primaryModel, { provider: "scripted", id: "primary-v2" });
	assert.equal(sent.evidence.length, 2);
	assert.deepEqual(sent.evidence.map((item) => item.outcome), ["failed", "incomplete"]);
	assert.ok(sent.evidence.every((item) => item.provenance.pointer.startsWith("pi-session://")));
	assert.ok(sent.evidence.every((item) => item.id.startsWith("pi-ev-")));
	assert.ok(sent.evidence.every((item) => item.provenance.context === "branch:main"));
	const serialized = JSON.stringify(sent);
	assert.doesNotMatch(serialized, /super-secret|another-secret|never-copy-this|\/Users\/alice/);
	assert.match(serialized, /Tool read — failed/);
	assert.ok(serialized.length < 12_000);
	await waitFor(async () => (await store.getOperationalState(enabled.sourceId)).pending.length === 0);
	const state = await store.getOperationalState(enabled.sourceId);
	assert.equal(state.cursor.seenEvidenceIds.length, 2);
	await bridge.captureSettled(ctx);
	assert.equal(scheduled.length, 1, "replayed settled activity is not scheduled twice");
});

test("threshold scheduling retries a drain when a new batch arrives during a below-threshold state read", async (t) => {
	const backingStore = await temporaryStore(t);
	const releaseStateRead = deferred();
	const releaseFirstSchedule = deferred();
	let pauseOnePendingRead = false;
	let pausedOnePendingRead = false;
	const store = {
		async getOperationalState(sourceId) {
			const state = await backingStore.getOperationalState(sourceId);
			if (pauseOnePendingRead && !pausedOnePendingRead && state.pending.length === 1) {
				pausedOnePendingRead = true;
				await releaseStateRead.promise;
			}
			return state;
		},
		updateOperationalState: (...args) => backingStore.updateOperationalState(...args),
		enqueuePending: (...args) => backingStore.enqueuePending(...args),
		completePending: (...args) => backingStore.completePending(...args),
	};
	const scheduled = [];
	let holdFirstSchedule = true;
	const bridge = createPiCaptureBridge({
		store,
		batchThreshold: 2,
		maxBatchEvidence: 1,
		now: () => 1_000_000,
		scheduleBatch: async (batch) => {
			scheduled.push(batch);
			if (holdFirstSchedule) {
				holdFirstSchedule = false;
				await releaseFirstSchedule.promise;
			}
		},
	});
	const pi = makePi();
	registerPiCaptureLifecycle(pi, bridge);
	const session = new ScriptedSession("threshold-race-session");
	const ctx = makeContext(session);
	const { sourceId } = await bridge.enable(ctx);

	addExchange(session, { user: "First queued request." });
	await pi.handlers.get("agent_settled")({}, ctx);
	addExchange(session, { user: "Second queued request." });
	await pi.handlers.get("agent_settled")({}, ctx);
	await waitFor(() => scheduled.length === 1, "initial threshold did not start a worker batch");

	// After the first one-item worker batch completes, freeze the drain's stale
	// one-item snapshot. The third capture will bring the durable queue to two
	// while the current drain still owns the source lock.
	pauseOnePendingRead = true;
	releaseFirstSchedule.resolve();
	await waitFor(() => pausedOnePendingRead, "active drain did not reach the below-threshold read");
	addExchange(session, { user: "Threshold-crossing request." });
	await pi.handlers.get("agent_settled")({}, ctx);
	releaseStateRead.resolve();

	await waitFor(() => scheduled.length === 2, "threshold-crossing capture was stranded behind an active drain");
	await waitFor(async () => (await backingStore.getOperationalState(sourceId)).pending.length === 1);
	assert.equal(scheduled[0].payload.evidence.length, 1);
	assert.equal(scheduled[1].payload.evidence.length, 1);
	assert.notEqual(scheduled[0].payload.evidence[0].id, scheduled[1].payload.evidence[0].id);
});

test("enabling an existing session seeds at its leaf instead of replaying history or making a first-exchange call", async (t) => {
	const store = await temporaryStore(t);
	const session = new ScriptedSession("existing-session");
	addExchange(session, { user: "An earlier unmonitored request.", assistant: "Do not replay this history." });
	const { bridge, pi, ctx, scheduled } = await startCapture({ store, session, threshold: 3 });
	const { sourceId } = await bridge.enable(ctx);
	const oldResult = await pi.handlers.get("agent_settled")({}, ctx);
	assert.equal(oldResult.reason, "before-enable");
	assert.equal(scheduled.length, 0);
	assert.equal((await store.getOperationalState(sourceId)).pending.length, 0);

	addExchange(session, { user: "A new monitored request.", assistant: "This is the first eligible exchange." });
	await pi.handlers.get("agent_settled")({}, ctx);
	const state = await store.getOperationalState(sourceId);
	assert.equal(state.pending.length, 1);
	assert.match(state.pending[0].payload.evidence[0].summary, /A new monitored request/);
	assert.doesNotMatch(state.pending[0].payload.evidence[0].summary, /earlier unmonitored request/);
	assert.equal(scheduled.length, 0);
});

test("resume recovers a persisted eligible exchange before advancing its capture boundary", async (t) => {
	const store = await temporaryStore(t);
	const session = new ScriptedSession("saved-unseen-session");
	const ctx = makeContext(session);
	const first = createPiCaptureBridge({ store, now: () => 1_000_000 });
	const { sourceId } = await first.enable(ctx);
	addExchange(session, { user: "Saved before the settled hook ran.", assistant: "This activity must survive restart." });
	assert.equal((await store.getOperationalState(sourceId)).pending.length, 0);

	const releaseSchedule = deferred();
	const scheduled = [];
	const { pi } = await startCapture({
		store, session, threshold: 3, now: () => 2_000_000,
		scheduleBatch: async (batch) => { scheduled.push(batch); await releaseSchedule.promise; },
	});
	const queued = await store.getOperationalState(sourceId);
	assert.equal(queued.pending.length, 1);
	assert.match(queued.pending[0].payload.evidence[0].summary, /Saved before the settled hook ran/);
	assert.deepEqual(queued.cursor.seenEvidenceIds, []);
	await waitFor(() => scheduled.length === 1, "resume did not schedule the recovered exchange below threshold");
	assert.equal(scheduled[0].payload.evidence.length, 1);
	releaseSchedule.resolve();
	await waitFor(async () => (await store.getOperationalState(sourceId)).pending.length === 0);
	await pi.handlers.get("session_start")({ reason: "resume" }, ctx);
	assert.equal(scheduled.length, 1, "a second resume must not duplicate recovered activity");
});

test("error attempts stay failed and rejected worker runs leave the checkpoint pending for retry", async (t) => {
	const store = await temporaryStore(t);
	const session = new ScriptedSession("error-session");
	const attempts = [];
	const errors = [];
	let rejectFirst = true;
	const bridge = createPiCaptureBridge({
		store,
		batchThreshold: 1,
		now: () => 1_000_000,
		onError: (error) => errors.push(error),
		scheduleBatch: async (batch) => {
			attempts.push(batch);
			if (rejectFirst) {
				rejectFirst = false;
				throw new Error("scripted observer abort");
			}
		},
	});
	const pi = makePi();
	registerPiCaptureLifecycle(pi, bridge);
	const ctx = makeContext(session);
	await bridge.enable(ctx);
	session.clock = 999_998; // The settled assistant timestamp equals the opt-in boundary.
	addExchange(session, { user: "Run the failing operation.", assistant: "The provider call failed.", stopReason: "error", assistantError: "provider error: API_KEY=secret-value" });
	await pi.handlers.get("agent_settled")({}, ctx);
	await waitFor(() => errors.length === 1);
	const sourceId = piSourceId(session.id);
	let state = await store.getOperationalState(sourceId);
	assert.equal(state.pending.length, 1);
	assert.deepEqual(state.cursor.seenEvidenceIds, []);
	assert.equal(state.pending[0].payload.evidence[0].outcome, "failed");
	assert.doesNotMatch(state.pending[0].payload.evidence[0].summary, /secret-value/);

	await bridge.flush(ctx);
	await waitFor(async () => (await store.getOperationalState(sourceId)).pending.length === 0);
	state = await store.getOperationalState(sourceId);
	assert.equal(attempts.length, 2);
	assert.deepEqual(state.cursor.seenEvidenceIds, [attempts[0].payload.evidence[0].id]);
});

test("/tree navigation captures only the active branch and gives it distinct stable provenance", async (t) => {
	const store = await temporaryStore(t);
	const session = new ScriptedSession("tree-session");
	const { bridge, pi, ctx, scheduled } = await startCapture({ store, session, threshold: 1 });
	const { sourceId } = await bridge.enable(ctx);
	const original = addExchange(session, { user: "Compare these approaches.", assistant: "Abandoned branch: used approach A." });
	await pi.handlers.get("agent_settled")({}, ctx);
	await waitFor(() => scheduled.length === 1);
	await waitFor(async () => (await store.getOperationalState(sourceId)).pending.length === 0);

	const oldBranch = session.getBranch();
	session.branch(original.userEntry.id);
	await pi.handlers.get("session_tree")({ newLeafId: original.userEntry.id, oldLeafId: oldBranch.at(-1).id }, ctx);
	session.add({ message: { role: "user", content: "Try a different approach." } });
	const alternate = session.add({ message: { role: "assistant", content: [{ type: "text", text: "New branch: used approach B." }], stopReason: "stop" } });
	await pi.handlers.get("agent_settled")({}, ctx);
	await waitFor(() => scheduled.length === 2);
	const mainEvidence = scheduled[0].payload.evidence[0];
	const branchEvidence = scheduled[1].payload.evidence[0];
	assert.notEqual(mainEvidence.id, branchEvidence.id);
	assert.notEqual(mainEvidence.provenance.context, branchEvidence.provenance.context);
	assert.match(branchEvidence.provenance.context, /^branch:[a-f0-9]+$/);
	assert.match(branchEvidence.provenance.pointer, /^pi-session:\/\/tree-session#e\d+$/);
	assert.match(JSON.stringify(scheduled[1].payload), /New branch: used approach B/);
	assert.doesNotMatch(JSON.stringify(scheduled[1].payload), /Abandoned branch: used approach A/);
	assert.equal(alternate.id, session.getLeafId());
	await waitFor(async () => (await store.getOperationalState(sourceId)).pending.length === 0);
});

test("off keeps already-pending evidence, refuses later automatic capture, and explicit flush bypasses threshold", async (t) => {
	const store = await temporaryStore(t);
	const session = new ScriptedSession("off-session");
	const { bridge, pi, ctx, scheduled, cancelled } = await startCapture({ store, session, threshold: 3 });
	const { sourceId } = await bridge.enable(ctx);
	addExchange(session);
	await pi.handlers.get("agent_settled")({}, ctx);
	assert.equal((await store.getOperationalState(sourceId)).pending.length, 1);

	await bridge.disable(ctx);
	assert.deepEqual(cancelled, [sourceId]);
	addExchange(session, { user: "This happened while off.", assistant: "No monitor work should be scheduled." });
	assert.equal((await bridge.captureSettled(ctx)).reason, "off");
	assert.equal(scheduled.length, 0);
	assert.equal((await store.getOperationalState(sourceId)).pending.length, 1);

	const flushed = await bridge.flush(ctx);
	assert.equal(flushed.scheduled, true);
	await waitFor(() => scheduled.length === 1);
	assert.equal(scheduled[0].explicit, true);
	assert.equal(scheduled[0].payload.evidence.length, 1);
	await waitFor(async () => (await store.getOperationalState(sourceId)).pending.length === 0);
	assert.equal((await bridge.status(ctx)).enabled, false);
});

test("ephemeral sessions refuse opt-in and observer-marked sessions are excluded from every entry point", async (t) => {
	const store = await temporaryStore(t);
	const ephemeral = new ScriptedSession("ephemeral", { persisted: false });
	const bridge = createPiCaptureBridge({ store });
	assert.deepEqual(await bridge.enable(makeContext(ephemeral)), { ok: false, reason: "ephemeral" });

	const worker = new ScriptedSession("observer");
	worker.addCustom(OBSERVER_SESSION_MARKER, { role: "observer", version: 1 });
	assert.equal(isObserverSession(worker), true);
	const workerCtx = makeContext(worker);
	assert.deepEqual(await bridge.enable(workerCtx), { ok: false, reason: "observer" });
	assert.deepEqual(await bridge.captureSettled(workerCtx), { ok: false, reason: "observer" });
	assert.equal((await store.listSources()).length, 0);
});

test("resume drains durable pending work; new and forked session IDs have independent disabled state", async (t) => {
	const store = await temporaryStore(t);
	const resumed = new ScriptedSession("resumed-session");
	const sourceId = piSourceId(resumed.id);
	await store.updateOperationalState(sourceId, { enabled: true, cursor: { version: 1, enabledAt: 1_000_000, seenEvidenceIds: [], lastLeafId: null } });
	const evidence = {
		id: "pi-ev-resume",
		summary: "A bounded prior exchange.",
		outcome: "completed",
		provenance: { pointer: "pi-session://opaque/pi-ev-resume", availability: "available", context: "branch-main" },
	};
	await store.enqueuePending(sourceId, {
		id: "pending-resume",
		payload: { source: { id: sourceId, label: "Pi session resume" }, evidence: [evidence] },
		cursorAfter: { version: 1, enabledAt: 1_000_000, seenEvidenceIds: [evidence.id], lastLeafId: null },
	});
	const scheduled = [];
	const bridge = createPiCaptureBridge({ store, batchThreshold: 3, scheduleBatch: async (batch) => { scheduled.push(batch); } });
	const pi = makePi();
	registerPiCaptureLifecycle(pi, bridge);
	await pi.handlers.get("session_start")({ reason: "resume" }, makeContext(resumed));
	await waitFor(() => scheduled.length === 1, "resumed pending batch was not scheduled below threshold");
	await waitFor(async () => (await store.getOperationalState(sourceId)).pending.length === 0);

	const forked = new ScriptedSession("forked-session");
	const forkState = await bridge.status(makeContext(forked));
	assert.notEqual(forkState.sourceId, sourceId);
	assert.equal(forkState.enabled, false);
	assert.equal((await bridge.enable(makeContext(forked))).sourceId, forkState.sourceId);
});

test("shutdown cancels owned work and returns without waiting for a worker/model promise", async (t) => {
	const store = await temporaryStore(t);
	const session = new ScriptedSession("shutdown-session");
	const pendingRun = new Promise(() => {});
	const scheduled = [];
	const cancelled = [];
	const { bridge, pi, ctx } = await startCapture({
		store,
		session,
		threshold: 1,
		scheduled,
		cancelled,
		scheduleBatch: (batch) => { scheduled.push(batch); return pendingRun; },
		cancelWorker: async (sourceId) => { cancelled.push(sourceId); },
	});
	const { sourceId } = await bridge.enable(ctx);
	addExchange(session);
	const settled = pi.handlers.get("agent_settled")({}, ctx);
	await Promise.race([settled, new Promise((_, reject) => setTimeout(() => reject(new Error("settled waited on worker")), 100))]);
	await waitFor(() => scheduled.length === 1);
	const shutdownReturn = pi.handlers.get("session_shutdown")({ reason: "quit" }, ctx);
	assert.equal(shutdownReturn, undefined);
	ctx.sessionManager = new Proxy({}, { get() { throw new Error("stale ExtensionContext used after shutdown callback"); } });
	await waitFor(() => cancelled.includes(sourceId));
	assert.equal((await store.getOperationalState(sourceId)).pending.length, 1);
});

test("branch provenance is stable for a branch route and source refs stay opaque", () => {
	const session = new ScriptedSession("opaque-session");
	const first = session.add({ message: { role: "user", content: "first" } });
	session.add({ message: { role: "assistant", content: [{ type: "text", text: "main" }], stopReason: "stop" } });
	const main = piBranchContext(session);
	session.branch(first.id);
	session.add({ message: { role: "user", content: "alternate" } });
	const alternate = piBranchContext(session);
	assert.equal(main, "branch:main");
	assert.equal(alternate, piBranchContext(session));
	assert.notEqual(main, alternate);
	assert.doesNotMatch(piSourceId("opaque-session"), /opaque-session/);
});
