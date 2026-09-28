import { reviewActivity } from "./core/index.mjs";
import {
	createPiCaptureBridge,
	registerPiCaptureLifecycle,
	privacyFilter,
} from "./capture.mjs";
import { createLearningsMonitorControls, DEFAULT_OBSERVER_TOOLS } from "./control.mjs";

const MAX_PROPOSALS = 12;
const MAX_PROPOSAL_CHARS = 700;
const MAX_MEMORY_LOOKUPS = 8;

function cancelledError() {
	return Object.assign(new Error("Observer work was cancelled"), { code: "aborted" });
}

function parseProposals(text) {
	let parsed;
	try {
		parsed = JSON.parse(String(text ?? ""));
	} catch (error) {
		throw new Error(`observer returned invalid JSON: ${error.message}`);
	}
	if (!parsed || typeof parsed !== "object" || !Array.isArray(parsed.proposals)) {
		throw new Error("observer response must contain a proposals array");
	}
	if (parsed.proposals.length > MAX_PROPOSALS) {
		throw new Error(`observer returned more than ${MAX_PROPOSALS} proposals`);
	}
	return parsed.proposals.map((proposal) => {
		if (!proposal || typeof proposal !== "object" || Array.isArray(proposal)) return proposal;
		return {
			...proposal,
			...(typeof proposal.observation === "string" ? { observation: privacyFilter(proposal.observation, MAX_PROPOSAL_CHARS) } : {}),
			...(typeof proposal.recommendation === "string" ? { recommendation: privacyFilter(proposal.recommendation, MAX_PROPOSAL_CHARS) } : {}),
		};
	});
}

/**
 * Connect primary Pi capture, the native observer, source-neutral review, and
 * the local Markdown store. Review commands can register through the returned
 * narrow `review` surface without owning lifecycle or control wiring.
 */
export function createLearningsMonitorRuntime(pi, {
	store,
	createWorker,
	memory = null,
	batchThreshold,
	registerReviewCommands,
} = {}) {
	if (!pi?.on || !pi?.registerCommand) throw new TypeError("Pi extension API is required");
	if (!store?.getOperationalState || !store?.readRecords || !store?.applyChanges) throw new TypeError("learning store is required");
	if (typeof createWorker !== "function") throw new TypeError("createWorker is required");

	const runners = new Map();
	const selectedTools = new Map();
	const cancellationEpoch = new Map();
	let controls;

	function getWorker(sourceId) {
		let runner = runners.get(sourceId);
		if (!runner) {
			runner = createWorker(selectedTools.get(sourceId) ?? [...DEFAULT_OBSERVER_TOOLS]);
			runners.set(sourceId, runner);
		}
		return runner;
	}

	function isCancelled(sourceId, epoch) {
		return (cancellationEpoch.get(sourceId) ?? 0) !== epoch;
	}

	async function processBatch(batch) {
		const { sourceId } = batch;
		const epoch = cancellationEpoch.get(sourceId) ?? 0;
		const result = await getWorker(sourceId).run(batch);
		if (isCancelled(sourceId, epoch)) throw cancelledError();
		const proposals = parseProposals(result?.text);
		if (proposals.length) {
			const records = await store.readRecords(sourceId);
			if (isCancelled(sourceId, epoch)) throw cancelledError();
			const candidates = proposals.filter((proposal) => reviewActivity({
				activity: batch.payload,
				proposals: [proposal],
				records,
			}).changes.length > 0);
			const relatedEvidence = [];
			for (const [index, proposal] of candidates.entries()) {
				if (!memory || index >= MAX_MEMORY_LOOKUPS) continue;
				const query = [proposal.observation, proposal.recommendation].filter((part) => typeof part === "string").join("\n").trim();
				if (!query) continue;
				let related;
				try {
					related = await memory.related(query);
				} catch (error) {
					if (isCancelled(sourceId, epoch)) throw cancelledError();
					controls.recordFailure(sourceId, "memory", error);
					continue;
				}
				if (isCancelled(sourceId, epoch)) throw cancelledError();
				if (related?.status === "failed") {
					controls.recordFailure(sourceId, "memory", new Error(`related-memory lookup failed (${related.error?.kind ?? "unknown"})`));
					continue;
				}
				controls.recordSuccess(sourceId, "memory");
				if (related?.status === "found" && Array.isArray(related.evidence)) {
					relatedEvidence.push(...related.evidence);
					proposal.relatedEvidenceIds = related.evidence.map((item) => item.id);
				}
			}

			const reviewed = reviewActivity({ activity: batch.payload, proposals, records, relatedEvidence });
			if (isCancelled(sourceId, epoch)) throw cancelledError();
			if (reviewed.changes.length) {
				await store.applyChanges(sourceId, reviewed.changes, {
					basedOn: records,
					label: batch.payload?.source?.label,
				});
				if (isCancelled(sourceId, epoch)) throw cancelledError();
			}
		}
		controls.recordSuccess(sourceId, "observer");
		return result;
	}

	async function cancelWorker(sourceId) {
		cancellationEpoch.set(sourceId, (cancellationEpoch.get(sourceId) ?? 0) + 1);
		const runner = runners.get(sourceId);
		if (!runner) return;
		return runner.abort(sourceId);
	}

	async function setTools(sourceId, tools) {
		cancellationEpoch.set(sourceId, (cancellationEpoch.get(sourceId) ?? 0) + 1);
		const current = runners.get(sourceId);
		if (current) {
			await current.close();
			runners.delete(sourceId);
		}
		selectedTools.set(sourceId, [...tools]);
	}

	const capture = createPiCaptureBridge({
		store,
		batchThreshold,
		scheduleBatch: processBatch,
		cancelWorker,
		onError(error, sourceId) {
			if (error?.code === "aborted" || error?.name === "AbortError") return;
			controls.recordFailure(sourceId, "observer", error);
		},
	});
	controls = createLearningsMonitorControls({
		capture,
		store,
		getWorker,
		getTools: (sourceId) => [...(selectedTools.get(sourceId) ?? DEFAULT_OBSERVER_TOOLS)],
		setTools,
	});

	registerPiCaptureLifecycle(pi, capture);
	controls.register(pi);
	pi.on("session_shutdown", () => {
		for (const [sourceId, runner] of runners) {
			cancellationEpoch.set(sourceId, (cancellationEpoch.get(sourceId) ?? 0) + 1);
			void runner.close().catch(() => {});
		}
	});

	const review = Object.freeze({
		store,
		memory,
		sourceStatus: (ctx) => capture.status(ctx),
		workerStats: (sourceId) => getWorker(sourceId).stats(sourceId),
		disposeWorker: (sourceId) => getWorker(sourceId).dispose(sourceId),
	});
	if (typeof registerReviewCommands === "function") registerReviewCommands(pi, review);

	return Object.freeze({
		capture,
		controls,
		review,
		getWorker,
		close: async () => {
			for (const [sourceId, runner] of runners) {
				cancellationEpoch.set(sourceId, (cancellationEpoch.get(sourceId) ?? 0) + 1);
				await runner.close();
			}
			runners.clear();
		},
	});
}

export { parseProposals };
