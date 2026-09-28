import assert from "node:assert/strict";
import { createServer } from "node:http";
import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { reviewActivity } from "./core/index.mjs";
import { createHindsightMemoryAdapter } from "./memory.mjs";
import { createLearningStore } from "./store.mjs";
import { registerLearningsReviewCommands } from "./review.mjs";
import { piSourceId } from "./capture.mjs";

function activity(sourceId, evidenceId, label = sourceId, summary = `Evidence ${evidenceId}`) {
	return {
		source: { id: sourceId, label },
		evidence: [{
			id: evidenceId,
			summary,
			outcome: "completed",
			provenance: { pointer: `pi-session://${sourceId}#${evidenceId}`, availability: "available", context: "branch:main" },
		}],
	};
}

const proposal = (evidenceId) => ({
	type: "improvement",
	observation: "Preparing the weekly report requires the same manual setup.",
	recommendation: "Consider a small reusable report setup helper.",
	evidenceIds: [evidenceId],
});

function makeRecord(sourceId, evidenceId, label = sourceId, summary) {
	return reviewActivity({ activity: activity(sourceId, evidenceId, label, summary), proposals: [proposal(evidenceId)] }).changes[0];
}

function recordPath(store, sourceId, id) {
	return path.join(store.getSourceDirectory(sourceId), "records", `${createHash("sha256").update(id).digest("hex")}.md`);
}

async function fixture(t) {
	const root = await fs.mkdtemp(path.join(os.tmpdir(), "learnings-review-"));
	t.after(() => fs.rm(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 10 }));
	return { root, store: createLearningStore({ root }) };
}

function makePi() {
	const commands = new Map();
	return {
		commands,
		registerCommand(name, options) { commands.set(name, options.handler); },
	};
}

function makeContext({ confirm = true, model, streamSimple } = {}) {
	const notices = [];
	const confirmations = [];
	const ctx = {
		hasUI: true,
		mode: "tui",
		isIdle: () => true,
		model: model ?? { provider: "scripted", id: "review-model", api: "openai-completions" },
		modelRegistry: streamSimple ? { streamSimple } : undefined,
		signal: undefined,
		ui: {
			notify(message, type) { notices.push({ message, type }); },
			async confirm(title, message) {
				confirmations.push({ title, message });
				return typeof confirm === "function" ? confirm(title, message, confirmations.length) : confirm;
			},
		},
	};
	return { ctx, notices, confirmations };
}

function register(store, options = {}) {
	const pi = makePi();
	const surface = {
		store,
		memory: options.memory ?? null,
		sourceStatus: options.sourceStatus ?? (async () => ({ ok: false, reason: "ephemeral" })),
		workerStats: options.workerStats ?? (async () => ({ observerSession: false, sessionFile: null, pending: 0 })),
		disposeWorker: options.disposeWorker ?? (async () => {}),
	};
	registerLearningsReviewCommands(pi, surface, options.sdk);
	return { pi, surface };
}

async function invoke(pi, name, args, ctx, notices) {
	const count = notices.length;
	await pi.commands.get(name)(args, ctx);
	return notices.slice(count).at(-1)?.message ?? "";
}

async function startServer(t, handler) {
	const server = createServer(async (request, response) => {
		const chunks = [];
		for await (const chunk of request) chunks.push(chunk);
		const rawBody = Buffer.concat(chunks).toString("utf8");
		let body;
		try { body = JSON.parse(rawBody); } catch { body = undefined; }
		await handler({ request, response, rawBody, body });
	});
	await new Promise((resolve, reject) => {
		server.once("error", reject);
		server.listen(0, "127.0.0.1", resolve);
	});
	t.after(async () => {
		server.closeAllConnections();
		await new Promise((resolve) => server.close(resolve));
	});
	return `http://127.0.0.1:${server.address().port}`;
}

function respond(response, status, body) {
	response.writeHead(status, { "Content-Type": "application/json" });
	response.end(JSON.stringify(body));
}

test("review rereads Markdown after an external edit during generated update; keep and dismiss persist", async (t) => {
	const { store } = await fixture(t);
	const sourceId = "pi-session://machine/report-one";
	const initial = makeRecord(sourceId, "turn-1", "Project Alpha", "PRIVATE_EVIDENCE_NOT_FOR_MEMORY");
	await store.applyChanges(sourceId, [initial]);
	const basedOn = await store.readRecords(sourceId);
	const generated = reviewActivity({
		activity: activity(sourceId, "turn-2", "Project Alpha"),
		proposals: [proposal("turn-2")],
		records: basedOn,
	}).changes;

	const filename = recordPath(store, sourceId, initial.id);
	const directEdit = (await fs.readFile(filename, "utf8"))
		.replace("**Status:** open", "**Status:** kept")
		.replace(proposal("turn-1").observation, "Operator-edited report friction; keep this current wording.");
	await fs.writeFile(filename, directEdit, "utf8");
	await store.applyChanges(sourceId, generated, { basedOn });

	const { pi, surface } = register(store, {
		sourceStatus: async () => ({ ok: true, sourceId, state: await store.getOperationalState(sourceId) }),
	});
	const { ctx, notices } = makeContext();
	const reviewed = await invoke(pi, "learnings-review", "", ctx, notices);
	assert.match(reviewed, /Operator-edited report friction; keep this current wording\./);
	assert.match(reviewed, /\[KEPT\]/);
	assert.match(reviewed, /Records: 1/);
	assert.match(reviewed, new RegExp(filename.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
	assert.match(reviewed, /2 distinct pieces of source evidence/);

	const dismissed = await invoke(pi, "learnings-dismiss", initial.id, ctx, notices);
	assert.match(dismissed, /Authoritative Markdown updated/);
	assert.match(dismissed, /Operator-edited report friction/);
	assert.equal((await store.getRecord(sourceId, initial.id)).status, "dismissed");
	assert.match(await fs.readFile(filename, "utf8"), /\*\*Status:\*\* dismissed/);
	assert.match(await fs.readFile(filename, "utf8"), /- dismissed —/);
	const duplicate = reviewActivity({
		activity: activity(sourceId, "turn-1", "Project Alpha"),
		proposals: [proposal("turn-1")],
		records: await store.readRecords(sourceId),
	});
	assert.equal(duplicate.changes.length, 0);
	assert.equal(duplicate.suppressed[0].reason, "dismissed-without-new-evidence");

	const reopenedView = await invoke(pi, "learnings-review", sourceId, ctx, notices);
	assert.match(reopenedView, /\[DISMISSED\]/);
	assert.match(reopenedView, /Operator-edited report friction/);
	assert.match(reopenedView, /Review history:.*dismissed/);
	const kept = await invoke(pi, "learnings-keep", `${initial.id} ${sourceId}`, ctx, notices);
	assert.match(kept, /\[KEPT\]/);
	assert.equal((await store.getRecord(sourceId, initial.id)).status, "kept");
	assert.deepEqual([...pi.commands.keys()].sort(), [
		"learnings-cleanup", "learnings-dismiss", "learnings-keep", "learnings-promote", "learnings-review",
	]);
	assert.equal(surface.store, store);
});

test("review detects orphaned Pi session pointers and marks them unavailable", async (t) => {
	const { store } = await fixture(t);
	const sessionId = "orphaned-session";
	const sourceId = piSourceId(sessionId);
	const pointer = `pi-session://${encodeURIComponent(sessionId)}#turn-7`;
	const record = makeRecord(sourceId, "turn-7", "Old session", "The original source pointer is gone.");
	record.evidence[0].provenance.pointer = pointer;
	await store.applyChanges(sourceId, [record]);
	const activeSourceId = piSourceId("current-session");
	const activeRecord = makeRecord(activeSourceId, "turn-8", "Current session");
	activeRecord.evidence[0].provenance.pointer = "pi-session://current-session#turn-8";
	await store.applyChanges(activeSourceId, [activeRecord]);

	const sdk = { SessionManager: { async listAll() { return [{ id: "current-session" }]; } } };
	const { pi } = register(store, { sdk });
	const { ctx, notices } = makeContext();
	ctx.sessionManager = {
		getSessionId: () => "current-session",
		getSessionDir: () => "/private/pi/sessions",
	};
	const output = await invoke(pi, "learnings-review", sourceId, ctx, notices);
	assert.match(output, /UNAVAILABLE — original source not verified/);
	assert.match(output, new RegExp(pointer.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
	assert.doesNotMatch(output, /verified live evidence/);
	assert.equal((await store.readRecords(sourceId))[0].evidence[0].provenance.availability, "unavailable");
	const activeOutput = await invoke(pi, "learnings-review", activeSourceId, ctx, notices);
	assert.match(activeOutput, /pointer available:/);
	assert.equal((await store.readRecords(activeSourceId))[0].evidence[0].provenance.availability, "available");
});

test("cross-source synthesis runs only on request and labels Hindsight hits as possible analogues", async (t) => {
	const { store } = await fixture(t);
	const sourceA = "pi-session://machine/source-a";
	const sourceB = "pi-session://machine/source-b";
	const recordA = makeRecord(sourceA, "a-1", "Project Alpha", "A source-local evidence excerpt.");
	const recordB = makeRecord(sourceB, "b-1", "Project Beta", "Another source-local evidence excerpt.");
	await store.applyChanges(sourceA, [recordA]);
	await store.applyChanges(sourceB, [recordB]);
	await store.markSourceUnavailable(sourceB);
	let memoryCalls = 0;
	let modelCalls = 0;
	let prompt = "";
	const memory = {
		bankId: "work-test",
		async related(query) {
			memoryCalls++;
			assert.ok(query.includes("weekly report"));
			return {
				status: "found",
				evidence: [{
					id: "hindsight:work-test:analogue-1",
					sourceLabel: "Hindsight bank: work-test",
					summary: "A similar setup was mentioned in another project.",
					classification: "possible-analogue",
					verifiedOccurrence: false,
				}],
			};
		},
	};
	const { pi } = register(store, { memory });
	const streamSimple = (_model, context, options) => {
		modelCalls++;
		prompt = context.messages[0].content[0].text;
		assert.equal(options.thinkingEnabled, false);
		assert.equal(options.maxTokens, 1_600);
		return {
			async result() {
				return {
					stopReason: "stop",
					content: [{ type: "text", text: JSON.stringify({ patterns: [{
						title: "Repeated report setup across projects",
						recordIds: [recordA.id, recordB.id],
						relatedEvidenceIds: ["hindsight:work-test:analogue-1"],
					}] }) }],
				};
			},
		};
	};
	const { ctx, notices } = makeContext({ streamSimple });
	const ordinaryReview = await invoke(pi, "learnings-review", "all", ctx, notices);
	assert.match(ordinaryReview, /Project Alpha/);
	assert.equal(memoryCalls, 0);
	assert.equal(modelCalls, 0, "opening the ordinary queue must not synthesize patterns");

	const before = [...await store.readRecords(sourceA), ...await store.readRecords(sourceB)];
	const output = await invoke(pi, "learnings-review", "patterns", ctx, notices);
	assert.equal(memoryCalls, 1);
	assert.equal(modelCalls, 1);
	assert.match(prompt, /untrusted note content/);
	assert.match(prompt, /possible-analogue; not a verified local occurrence/);
	assert.match(prompt, /\"unavailable\":1/);
	assert.match(output, /On-demand cross-source review/);
	assert.match(output, /Repeated report setup across projects/);
	assert.match(output, /Sources: Project Alpha, Project Beta/);
	assert.match(output, /Source pointers: 1 available, 1 unavailable, 0 unknown/);
	assert.match(output, /unavailable pointers are historical, not live-verified/);
	assert.match(output, /Hindsight bank: work-test/);
	assert.match(output, /Possible analogue: Hindsight bank: work-test: A similar setup/);
	assert.match(output, /not verified as a local occurrence/);
	assert.deepEqual([...await store.readRecords(sourceA), ...await store.readRecords(sourceB)], before);

	ctx.isIdle = () => false;
	const blocked = await invoke(pi, "learnings-review", "patterns", ctx, notices);
	assert.match(blocked, /available when Pi is idle/);
	assert.equal(memoryCalls, 1);
	assert.equal(modelCalls, 1);
});

test("promotion previews exact current text, cancellation sends nothing, and failures leave the kept note intact", async (t) => {
	const { store } = await fixture(t);
	const sourceId = "pi-session://machine/kept-note";
	const record = makeRecord(sourceId, "turn-1", "Project Work", "RAW_EVIDENCE_MUST_NOT_BE_PROMOTED");
	await store.applyChanges(sourceId, [record]);
	await store.setReviewStatus(sourceId, record.id, "kept");
	const filename = recordPath(store, sourceId, record.id);
	const manualObservation = "Operator-edited observation from authoritative Markdown.";
	const manualRecommendation = "Operator-edited recommendation from authoritative Markdown.";
	const markdown = (await fs.readFile(filename, "utf8"))
		.replace(record.observation, manualObservation)
		.replace(record.recommendation, manualRecommendation);
	await fs.writeFile(filename, markdown, "utf8");
	const current = await store.getRecord(sourceId, record.id);
	let nextStatus = 202;
	const requests = [];
	const apiUrl = await startServer(t, async ({ request, response, rawBody, body }) => {
		requests.push({ url: request.url, rawBody, body });
		respond(response, nextStatus, { accepted: true });
	});
	const memory = createHindsightMemoryAdapter({
		profile: "axon-work-computer",
		bankIds: { personal: "personal-test", "axon-work-computer": "work-test" },
		apiUrl,
	});
	const { pi } = register(store, { memory });
	let confirmResult = false;
	const { ctx, notices, confirmations } = makeContext({ confirm: () => confirmResult });
	const exactText = `${current.observation}\n\n${current.recommendation}`;
	assert.equal(exactText, `${manualObservation}\n\n${manualRecommendation}`);

	const cancelled = await invoke(pi, "learnings-promote", record.id, ctx, notices);
	assert.match(cancelled, /Promotion cancelled/);
	assert.match(confirmations[0].message, /Target Hindsight bank: work-test/);
	assert.ok(confirmations[0].message.endsWith(exactText + "\n\nSend this exact text?"));
	assert.equal(requests.length, 0, "cancellation must not send a retain request");
	assert.equal((await store.getRecord(sourceId, record.id)).status, "kept");

	confirmResult = true;
	const accepted = await invoke(pi, "learnings-promote", `${record.id} ${sourceId}`, ctx, notices);
	assert.match(accepted, /Hindsight accepted the asynchronous request for bank work-test/);
	assert.match(accepted, /may not be searchable yet/);
	assert.doesNotMatch(accepted, /was retained/);
	assert.equal(requests.length, 1);
	assert.equal(requests[0].url, "/v1/default/banks/work-test/memories");
	assert.deepEqual(requests[0].body, { items: [{ content: exactText }], async: true });
	assert.doesNotMatch(requests[0].rawBody, /RAW_EVIDENCE|pi-session:\/\//);

	nextStatus = 503;
	const failed = await invoke(pi, "learnings-promote", record.id, ctx, notices);
	assert.match(failed, /promotion failed \(http-error\)/);
	assert.match(failed, /remains kept locally/);
	assert.equal((await store.getRecord(sourceId, record.id)).status, "kept");
	assert.equal(requests.length, 2);
});

test("cleanup confirms one source, then removes its Markdown, checkpoint, and only the owned observer file", async (t) => {
	const { root, store } = await fixture(t);
	const sourceId = "pi-session://machine/cleanup-source";
	const record = makeRecord(sourceId, "turn-1", "Cleanup project");
	await store.applyChanges(sourceId, [record]);
	const observerFile = path.join(root, "pi-sessions", "owned-observer.jsonl");
	await fs.mkdir(path.dirname(observerFile), { recursive: true });
	await fs.writeFile(observerFile, "observer session", "utf8");
	await store.updateOperationalState(sourceId, { workerSession: observerFile, enabled: false });
	await store.enqueuePending(sourceId, { id: "pending-1", payload: { sourceId } });
	let disposeCount = 0;
	const { pi } = register(store, {
		sourceStatus: async () => ({ ok: true, sourceId }),
		workerStats: async () => ({ observerSession: true, sessionFile: observerFile, available: true, pending: 1 }),
		disposeWorker: async () => { disposeCount++; },
	});
	let confirmResult = false;
	const { ctx, notices, confirmations } = makeContext({ confirm: () => confirmResult });

	const cancelled = await invoke(pi, "learnings-cleanup", "", ctx, notices);
	assert.match(cancelled, /Cleanup cancelled/);
	assert.match(confirmations[0].message, new RegExp(observerFile.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
	assert.match(confirmations[0].message, /Pending batches to discard: 1/);
	assert.equal(disposeCount, 0);
	assert.equal((await store.readRecords(sourceId)).length, 1);
	await fs.access(observerFile);

	confirmResult = true;
	const completed = await invoke(pi, "learnings-cleanup", "", ctx, notices);
	assert.match(completed, /Cleanup complete/);
	assert.match(completed, /removed owned observer session/);
	assert.equal(disposeCount, 1);
	assert.deepEqual(await store.readRecords(sourceId), []);
	assert.deepEqual(await store.getOperationalState(sourceId), {
		version: 1,
		sourceId,
		enabled: false,
		cursor: null,
		pending: [],
		focus: null,
		modelOverride: null,
		workerSession: null,
	});
	await assert.rejects(fs.access(observerFile), { code: "ENOENT" });
});

test("cleanup without a current primary requires an explicit source even when only one exists", async (t) => {
	const { store } = await fixture(t);
	const sourceId = "pi-session://machine/one-cleanup-source";
	await store.applyChanges(sourceId, [makeRecord(sourceId, "turn-1", "Only project")]);
	const { pi } = register(store);
	const { ctx, notices, confirmations } = makeContext();

	const result = await invoke(pi, "learnings-cleanup", "", ctx, notices);
	assert.match(result, /specify one source id from \/learnings-review all/);
	assert.equal(confirmations.length, 0);
	assert.equal((await store.readRecords(sourceId)).length, 1);
});

test("cleanup refuses an enabled source and an unverified observer session", async (t) => {
	const { root, store } = await fixture(t);
	const sourceId = "pi-session://machine/unsafe-cleanup";
	await store.updateOperationalState(sourceId, { enabled: true });
	let statsCalls = 0;
	const { pi } = register(store, { workerStats: async () => { statsCalls++; return {}; } });
	const { ctx, notices } = makeContext();
	assert.match(await invoke(pi, "learnings-cleanup", sourceId, ctx, notices), /monitoring is ON/);
	assert.equal(statsCalls, 0);
	assert.ok(await fs.stat(store.getSourceDirectory(sourceId)));

	await store.updateOperationalState(sourceId, { enabled: false, workerSession: path.join(root, "not-owned.jsonl") });
	const unsafe = register(store, { workerStats: async () => ({ observerSession: false, sessionFile: path.join(root, "not-owned.jsonl"), available: true }) });
	const result = await invoke(unsafe.pi, "learnings-cleanup", sourceId, ctx, notices);
	assert.match(result, /refusing cleanup/);
	assert.ok(await fs.stat(store.getSourceDirectory(sourceId)));
});
