import assert from "node:assert/strict";
import { createServer } from "node:http";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { reviewActivity } from "./core/index.mjs";
import { createLearningStore } from "./store.mjs";
import { createHindsightMemoryAdapter, resolveMemoryBank } from "./memory.mjs";

async function startServer(t, handler) {
	const server = createServer(async (request, response) => {
		const chunks = [];
		for await (const chunk of request) chunks.push(chunk);
		const rawBody = Buffer.concat(chunks).toString("utf8");
		let body;
		try {
			body = rawBody ? JSON.parse(rawBody) : undefined;
		} catch {
			body = undefined;
		}
		try {
			await handler({ request, response, body, rawBody });
		} catch (error) {
			if (!response.destroyed) {
				response.writeHead(500, { "Content-Type": "application/json" });
				response.end(JSON.stringify({ error: error.message }));
			}
		}
	});
	await new Promise((resolve, reject) => {
		server.once("error", reject);
		server.listen(0, "127.0.0.1", resolve);
	});
	t.after(async () => {
		server.closeAllConnections();
		await new Promise((resolve) => server.close(resolve));
	});
	const address = server.address();
	return `http://127.0.0.1:${address.port}`;
}

function sendJson(response, status, value) {
	response.writeHead(status, { "Content-Type": "application/json" });
	response.end(JSON.stringify(value));
}

function candidate() {
	return reviewActivity({
		activity: {
			source: { id: "pi-session://local/one", label: "Local session" },
			evidence: [{
				id: "failed-turn",
				summary: "A preexisting formatter setup issue.",
				outcome: "failed",
				provenance: { pointer: "pi-session://local/one#failed-turn", availability: "available" },
			}],
		},
		proposals: [{
			type: "friction",
			observation: "The formatter could not run without configuration.",
			evidenceIds: ["failed-turn"],
		}],
	}).changes[0];
}

test("related lookup bounds its query/results and labels Hindsight hits as unverified analogues", async (t) => {
	let received;
	const apiUrl = await startServer(t, ({ request, response, body }) => {
		received = { method: request.method, url: request.url, body };
		sendJson(response, 200, {
			results: Array.from({ length: 8 }, (_, index) => ({
				id: `memory-${index}`,
				text: index === 0 ? "x".repeat(400) : `Related workflow ${index}`,
			})),
		});
	});
	const adapter = createHindsightMemoryAdapter({
		profile: "personal",
		apiUrl,
		maxResults: 2,
		maxQueryChars: 12,
	});

	const result = await adapter.related("   12345678901234567890   ");
	assert.equal(received.method, "POST");
	assert.equal(received.url, "/v1/default/banks/cartwmic/memories/recall");
	assert.equal(received.body.query, "123456789012");
	assert.equal(received.body.budget, "low");
	assert.equal(result.status, "found");
	assert.equal(result.evidence.length, 2);
	assert.equal(result.evidence[0].summary.length, 240);
	assert.equal(result.evidence[0].sourceLabel, "Hindsight bank: cartwmic");
	assert.equal(result.evidence[0].classification, "possible-analogue");
	assert.equal(result.evidence[0].verifiedOccurrence, false);
	assert.equal(result.evidence[0].sourcePointer, "hindsight://banks/cartwmic/memories/memory-0");
	assert.equal(result.evidence[1].classification, "possible-analogue");
});

test("timeout fails open and leaves an already persisted local opportunity unchanged", async (t) => {
	const root = await fs.mkdtemp(path.join(os.tmpdir(), "learnings-monitor-memory-"));
	t.after(() => fs.rm(root, { recursive: true, force: true }));
	const store = createLearningStore({ root });
	const record = candidate();
	await store.applyChanges("pi-session://local/one", [record]);
	const before = await store.readRecords("pi-session://local/one");

	const apiUrl = await startServer(t, async ({ response }) => {
		await new Promise((resolve) => setTimeout(resolve, 150));
		if (!response.destroyed) sendJson(response, 200, { results: [] });
	});
	const adapter = createHindsightMemoryAdapter({ profile: "personal", apiUrl, requestTimeoutMs: 25 });
	const result = await adapter.related("manual formatter configuration");

	assert.deepEqual(result, { status: "failed", evidence: [], error: { kind: "timeout" } });
	assert.deepEqual(await store.readRecords("pi-session://local/one"), before);
	assert.equal((await store.getRecord("pi-session://local/one", record.id)).observation, record.observation);
});

test("HTTP and invalid-response failures are reported without leaking response payloads", async (t) => {
	let nextStatus = 503;
	const apiUrl = await startServer(t, ({ response }) => {
		if (nextStatus === 503) {
			response.writeHead(503, { "Content-Type": "application/json" });
			response.end(JSON.stringify({ detail: "server-specific response" }));
		} else {
			response.writeHead(200, { "Content-Type": "application/json" });
			response.end("not-json");
		}
	});
	const adapter = createHindsightMemoryAdapter({ profile: "personal", apiUrl, requestTimeoutMs: 500 });

	assert.deepEqual(await adapter.related("query"), {
		status: "failed",
		evidence: [],
		error: { kind: "http-error" },
	});
	nextStatus = 200;
	assert.deepEqual(await adapter.related("query"), {
		status: "failed",
		evidence: [],
		error: { kind: "invalid-response" },
	});
});

test("profile banks stay isolated for lookup and confirmed exact-text promotion", async (t) => {
	const requests = [];
	const apiUrl = await startServer(t, async ({ request, response, body, rawBody }) => {
		requests.push({ method: request.method, url: request.url, body, rawBody });
		if (request.url.endsWith("/recall")) sendJson(response, 200, { results: [] });
		else sendJson(response, 202, { accepted: true });
	});
	const bankIds = { personal: "personal-test", "axon-work-computer": "work-test" };
	const personal = createHindsightMemoryAdapter({ profile: "personal", apiUrl, bankIds });
	const work = createHindsightMemoryAdapter({ profile: "axon-work-computer", apiUrl, bankIds });
	assert.equal(resolveMemoryBank("personal", bankIds), "personal-test");
	assert.equal(resolveMemoryBank("axon-work-computer", bankIds), "work-test");
	assert.throws(() => resolveMemoryBank("termux", bankIds), /no Hindsight bank/);

	assert.equal((await personal.related("personal query")).status, "empty");
	assert.equal((await work.related("work query")).status, "empty");

	const record = {
		status: "kept",
		observation: "Repeated report setup is manual.",
		recommendation: "Consider a reusable script.",
		evidence: [{ summary: "RAW_EVIDENCE_MUST_NOT_BE_INCLUDED", provenance: { pointer: "/private/file" } }],
	};
	const exactText = "Operator-confirmed text only, verbatim.\nSecond line.";
	const personalPreview = personal.previewPromotion(record, exactText);
	assert.equal(personalPreview.text, exactText);
	assert.equal(personalPreview.bankId, "personal-test");
	assert.doesNotMatch(personal.previewPromotion(record).text, /RAW_EVIDENCE|private\/file/);
	assert.throws(() => personal.previewPromotion({ ...record, status: "open" }), /only a kept opportunity/);

	const cancelled = await personal.retainConfirmed(personal.confirmPromotion(personalPreview, false));
	assert.deepEqual(cancelled, { status: "cancelled" });
	assert.equal(requests.filter((request) => !request.url.endsWith("/recall")).length, 0);

	const personalPayload = personal.confirmPromotion(personalPreview, true);
	const personalResult = await personal.retainConfirmed(personalPayload);
	assert.equal(personalResult.status, "accepted");
	assert.equal(personalResult.bankId, "personal-test");
	assert.doesNotMatch(personalResult.status, /retained/);
	assert.deepEqual(requests.at(-1).body, { items: [{ content: exactText }], async: true });
	assert.equal(requests.at(-1).url, "/v1/default/banks/personal-test/memories");
	assert.doesNotMatch(requests.at(-1).rawBody, /RAW_EVIDENCE|private\/file/);
	assert.deepEqual(await personal.retainConfirmed(personalPayload), { status: "rejected", reason: "not-confirmed" });

	const workPreview = work.previewPromotion(record);
	const workPayload = work.confirmPromotion(workPreview, true);
	const workResult = await work.retainConfirmed(workPayload);
	assert.equal(workResult.status, "accepted");
	assert.equal(workResult.bankId, "work-test");
	assert.equal(requests.at(-1).url, "/v1/default/banks/work-test/memories");
	assert.deepEqual(requests.at(-1).body, {
		items: [{ content: "Repeated report setup is manual.\n\nConsider a reusable script." }],
		async: true,
	});
});

test("promotion reports server acceptance or failure without claiming immediate retention", async (t) => {
	let status = 202;
	const apiUrl = await startServer(t, ({ response }) => {
		response.writeHead(status, { "Content-Type": "application/json" });
		response.end(JSON.stringify({ accepted: true }));
	});
	const adapter = createHindsightMemoryAdapter({ profile: "personal", apiUrl });
	const record = { status: "kept", observation: "A reviewed local opportunity." };
	const preview = adapter.previewPromotion(record);
	const accepted = await adapter.retainConfirmed(adapter.confirmPromotion(preview, true));
	assert.equal(accepted.status, "accepted");
	assert.match(accepted.message, /may not be searchable yet/);
	assert.equal("retained" in accepted, false);

	status = 503;
	const failed = await adapter.retainConfirmed(adapter.confirmPromotion(preview, true));
	assert.deepEqual(failed, { status: "failed", error: { kind: "http-error" } });
});
