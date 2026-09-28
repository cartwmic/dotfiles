import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { reviewActivity } from "./core/index.mjs";
import { createLearningStore, defaultStoreRoot } from "./store.mjs";

const sourceId = "pi-session://machine/session-one";
const proposal = {
	type: "friction",
	observation: "The formatter could not run without configuration.",
	evidenceIds: ["turn-1"],
};

function activity(id, summary = `Evidence ${id}`) {
	return {
		source: { id: sourceId, label: "Session one" },
		evidence: [{
			id,
			summary,
			outcome: "failed",
			provenance: { pointer: `pi-session://session-one#${id}`, availability: "available", context: "branch:experiment" },
		}],
	};
}

function candidate(evidenceId = "turn-1") {
	return reviewActivity({
		activity: activity(evidenceId),
		proposals: [{ ...proposal, evidenceIds: [evidenceId] }],
	}).changes;
}

async function fixture(t) {
	const root = await fs.mkdtemp(path.join(os.tmpdir(), "learnings-monitor-store-"));
	t.after(() => fs.rm(root, { recursive: true, force: true }));
	return { root, store: createLearningStore({ root }) };
}

function markdownPath(store, source, id) {
	const name = `${createHash("sha256").update(id).digest("hex")}.md`;
	return path.join(store.getSourceDirectory(source), "records", name);
}

test("local Markdown is source-scoped, discoverable, and readable outside the source tree", async (t) => {
	const { root, store } = await fixture(t);
	const [record] = candidate();
	await store.applyChanges(sourceId, [record], { label: "Primary session" });
	const sources = await store.listSources();
	assert.equal(sources.length, 1);
	assert.equal(sources[0].sourceId, sourceId);
	assert.equal(sources[0].label, "Primary session");
	assert.equal(sources[0].recordCount, 1);
	assert.equal(path.dirname(sources[0].path), path.join(root, "sources"));
	assert.match(await fs.readFile(markdownPath(store, sourceId, record.id), "utf8"), /The formatter could not run/);
	assert.deepEqual(await store.readRecords("another-session"), []);
	assert.equal(defaultStoreRoot({ env: {}, home: "/home/operator" }), "/home/operator/.local/share/pi/learnings-monitor");
	assert.equal(defaultStoreRoot({ env: { XDG_DATA_HOME: "relative" }, home: "/home/operator" }), "/home/operator/.local/share/pi/learnings-monitor");
	assert.equal(defaultStoreRoot({ env: { XDG_DATA_HOME: "/data" }, home: "/home/operator" }), "/data/pi/learnings-monitor");
});

test("fresh generated updates preserve Markdown text/status edits and merge only new evidence", async (t) => {
	const { store } = await fixture(t);
	const [initial] = candidate();
	await store.applyChanges(sourceId, [initial]);
	const filename = markdownPath(store, sourceId, initial.id);
	const edited = (await fs.readFile(filename, "utf8"))
		.replace("**Status:** open", "**Status:** kept")
		.replace("The formatter could not run without configuration.", "Operator-edited finding; retain this exact wording.");
	await fs.writeFile(filename, edited, "utf8");

	const beforeReview = await store.readRecords(sourceId);
	assert.equal(beforeReview[0].status, "kept");
	assert.equal(beforeReview[0].observation, "Operator-edited finding; retain this exact wording.");
	const generated = reviewActivity({ activity: activity("turn-2"), proposals: [{ ...proposal, evidenceIds: ["turn-2"] }], records: beforeReview }).changes;
	assert.equal(generated.length, 1);
	await store.applyChanges(sourceId, generated, { basedOn: beforeReview });

	const saved = (await store.readRecords(sourceId))[0];
	assert.equal(saved.observation, "Operator-edited finding; retain this exact wording.");
	assert.equal(saved.status, "kept");
	assert.equal(saved.evidence.length, 2);
	assert.deepEqual(saved.evidence.map((item) => item.key), [initial.evidence[0].key, generated[0].evidence[1].key]);
	const markdown = await fs.readFile(filename, "utf8");
	assert.match(markdown, /Operator-edited finding; retain this exact wording\./);
	assert.match(markdown, /\*\*Status:\*\* kept/);
});

test("an external edit during review wins while generated evidence and dismissal history are retained", async (t) => {
	const { store } = await fixture(t);
	const [initial] = candidate();
	await store.applyChanges(sourceId, [initial]);
	const basedOn = await store.readRecords(sourceId);
	const generated = reviewActivity({ activity: activity("turn-2"), proposals: [{ ...proposal, evidenceIds: ["turn-2"] }], records: basedOn }).changes;
	const filename = markdownPath(store, sourceId, initial.id);
	const externalEdit = (await fs.readFile(filename, "utf8"))
		.replace("**Status:** open", "**Status:** dismissed")
		.replace("The formatter could not run without configuration.", "Dismissed by direct Markdown edit.");
	await fs.writeFile(filename, externalEdit, "utf8");

	await store.applyChanges(sourceId, generated, { basedOn });
	const saved = (await store.readRecords(sourceId))[0];
	assert.equal(saved.status, "dismissed");
	assert.equal(saved.observation, "Dismissed by direct Markdown edit.");
	assert.equal(saved.evidence.length, 2);
	assert.ok(saved.reviewHistory.some((event) => event.status === "dismissed"));
});

test("new evidence reopens a dismissal without deleting its history", async (t) => {
	const { store } = await fixture(t);
	const [initial] = candidate();
	await store.applyChanges(sourceId, [initial]);
	await store.setReviewStatus(sourceId, initial.id, "dismissed", { at: "2030-01-01T00:00:00Z" });
	const basedOn = await store.readRecords(sourceId);
	const generated = reviewActivity({ activity: activity("turn-2"), proposals: [{ ...proposal, evidenceIds: ["turn-2"] }], records: basedOn }).changes;
	assert.equal(generated[0].status, "open");
	await store.applyChanges(sourceId, generated, { basedOn });
	const saved = (await store.readRecords(sourceId))[0];
	assert.equal(saved.status, "open");
	assert.deepEqual(saved.reviewHistory.map((event) => event.status), ["dismissed", "open"]);
});

test("orphaned temporary files from an interrupted replacement do not corrupt committed state", async (t) => {
	const { root, store } = await fixture(t);
	await store.updateOperationalState(sourceId, { enabled: true, cursor: { turn: 4 } });
	const circular = {};
	circular.self = circular;
	await assert.rejects(store.updateOperationalState(sourceId, { cursor: circular }), /circular/i);
	const directory = store.getSourceDirectory(sourceId);
	await fs.writeFile(path.join(directory, "operational.json.interrupted.tmp"), '{"enabled": false', "utf8");

	const resumed = createLearningStore({ root });
	const state = await resumed.getOperationalState(sourceId);
	assert.equal(state.enabled, true);
	assert.deepEqual(state.cursor, { turn: 4 });
	const mode = (await fs.stat(path.join(directory, "operational.json"))).mode & 0o777;
	assert.equal(mode, 0o600);
});

test("pending replay is idempotent across a crash after Markdown write and before cursor commit", async (t) => {
	const { root, store } = await fixture(t);
	const firstChange = candidate();
	await store.enqueuePending(sourceId, { id: "batch-1", payload: { evidence: ["turn-1"] }, cursorAfter: { turn: 1 } });
	await store.enqueuePending(sourceId, { id: "batch-1", payload: { evidence: ["turn-1"] }, cursorAfter: { turn: 1 } });
	assert.equal((await store.getOperationalState(sourceId)).pending.length, 1);
	await store.applyChanges(sourceId, firstChange);

	// Simulate process death here: the Markdown commit succeeded, but the pending
	// batch and cursor are deliberately left untouched on disk.
	const resumed = createLearningStore({ root });
	let state = await resumed.getOperationalState(sourceId);
	assert.equal(state.pending.length, 1);
	assert.equal(state.cursor, null);
	const records = await resumed.readRecords(sourceId);
	const replay = reviewActivity({ activity: activity("turn-1"), proposals: proposal.evidenceIds ? [proposal] : [], records });
	assert.equal(replay.changes.length, 0);
	await resumed.applyChanges(sourceId, replay.changes, { basedOn: records });
	assert.equal((await resumed.readRecords(sourceId))[0].evidence.length, 1);

	state = await resumed.completePending(sourceId, "batch-1");
	assert.deepEqual(state.cursor, { turn: 1 });
	assert.deepEqual(state.pending, []);
});

test("pending batches cannot be replaced by conflicting replays and only the queue head commits", async (t) => {
	const { store } = await fixture(t);
	await store.enqueuePending(sourceId, { id: "first", payload: { n: 1 }, cursorAfter: 1 });
	await store.enqueuePending(sourceId, { id: "second", payload: { n: 2 }, cursorAfter: 2 });
	await assert.rejects(store.enqueuePending(sourceId, { id: "first", payload: { n: 99 }, cursorAfter: 1 }), /ID collision/);
	await assert.rejects(store.completePending(sourceId, "second"), /queue head/);
	const state = await store.completePending(sourceId, "first");
	assert.equal(state.cursor, 1);
	assert.deepEqual(state.pending.map((item) => item.id), ["second"]);
});

test("disabled resume retains pending work, focus, model override, and worker association", async (t) => {
	const { root, store } = await fixture(t);
	await store.updateOperationalState(sourceId, {
		enabled: true,
		focus: "Watch repeated report setup",
		modelOverride: "provider/model-id",
		workerSession: "/sessions/observer.jsonl",
		cursor: { turn: 8 },
	});
	await store.enqueuePending(sourceId, { id: "waiting", payload: { activity: [] }, cursorAfter: { turn: 9 } });
	await store.updateOperationalState(sourceId, { enabled: false });

	const resumed = createLearningStore({ root });
	const state = await resumed.getOperationalState(sourceId);
	assert.equal(state.enabled, false);
	assert.equal(state.focus, "Watch repeated report setup");
	assert.equal(state.modelOverride, "provider/model-id");
	assert.equal(state.workerSession, "/sessions/observer.jsonl");
	assert.deepEqual(state.cursor, { turn: 8 });
	assert.equal(state.pending.length, 1);
});

test("missing original source pointers remain visible and marked unavailable", async (t) => {
	const { store } = await fixture(t);
	const [record] = candidate();
	await store.applyChanges(sourceId, [record]);
	assert.equal(await store.markSourceUnavailable(sourceId), 1);
	assert.equal(await store.markSourceUnavailable(sourceId), 0);
	const saved = (await store.readRecords(sourceId))[0];
	assert.equal(saved.evidence[0].provenance.pointer, "pi-session://session-one#turn-1");
	assert.equal(saved.evidence[0].provenance.availability, "unavailable");
	assert.match(await fs.readFile(markdownPath(store, sourceId, record.id), "utf8"), /Pointer availability: `unavailable`/);
});

test("keep/dismiss commands edit authoritative Markdown history and cleanup is source-scoped", async (t) => {
	const { store } = await fixture(t);
	const [record] = candidate();
	await store.applyChanges(sourceId, [record]);
	const dismissed = await store.setReviewStatus(sourceId, record.id, "dismissed", { at: "2030-01-01T00:00:00Z" });
	assert.equal(dismissed.status, "dismissed");
	assert.equal((await store.getRecord(sourceId, record.id)).reviewHistory[0].status, "dismissed");
	await store.applyChanges("other-source", [candidateForSource("other-source")]);
	assert.equal(await store.cleanupSource(sourceId), true);
	assert.deepEqual(await store.readRecords(sourceId), []);
	assert.equal((await store.listSources()).some((item) => item.sourceId === "other-source"), true);
});

function candidateForSource(id) {
	return reviewActivity({
		activity: { source: { id }, evidence: [{ id: "e1", summary: "evidence", provenance: { pointer: "source://e1" } }] },
		proposals: [{ type: "friction", observation: "Another source observation.", evidenceIds: ["e1"] }],
	}).changes[0];
}
