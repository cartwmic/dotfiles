// Source-neutral opportunity logic. Keep this module free of Pi and memory-provider imports.

const OUTCOMES = new Set(["completed", "failed", "incomplete", "unknown"]);
const AVAILABILITY = new Set(["available", "unavailable", "unknown"]);
const MAX_EXCERPT_LENGTH = 240;

function isObject(value) {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requiredText(value, name) {
	if (typeof value !== "string" || value.trim().length === 0) {
		throw new TypeError(`${name} must be a non-empty string`);
	}
	return value.trim();
}

function optionalText(value, name) {
	if (value === undefined || value === null) return undefined;
	if (typeof value !== "string") throw new TypeError(`${name} must be a string`);
	const text = value.trim();
	return text.length > 0 ? text : undefined;
}

function shortText(value) {
	return value.trim().slice(0, MAX_EXCERPT_LENGTH);
}

function evidenceKey(sourceId, evidenceId) {
	return JSON.stringify([sourceId, evidenceId]);
}

function normalizeActivity(activity) {
	if (!isObject(activity)) throw new TypeError("activity must be an object");
	if (!isObject(activity.source)) throw new TypeError("activity.source must be an object");
	const sourceId = requiredText(activity.source.id, "activity.source.id");
	const sourceLabel = optionalText(activity.source.label, "activity.source.label") ?? sourceId;
	if (!Array.isArray(activity.evidence)) throw new TypeError("activity.evidence must be an array");

	const evidence = new Map();
	for (const [index, item] of activity.evidence.entries()) {
		if (!isObject(item)) throw new TypeError(`activity.evidence[${index}] must be an object`);
		const id = requiredText(item.id, `activity.evidence[${index}].id`);
		if (evidence.has(id)) throw new TypeError(`duplicate activity evidence id: ${id}`);
		const summary = requiredText(item.summary, `activity.evidence[${index}].summary`);
		if (!isObject(item.provenance)) {
			throw new TypeError(`activity.evidence[${index}].provenance must be an object`);
		}
		const pointer = requiredText(item.provenance.pointer, `activity.evidence[${index}].provenance.pointer`);
		const outcome = item.outcome ?? "unknown";
		if (!OUTCOMES.has(outcome)) throw new TypeError(`invalid activity outcome: ${outcome}`);
		const availability = item.provenance.availability ?? "unknown";
		if (!AVAILABILITY.has(availability)) throw new TypeError(`invalid provenance availability: ${availability}`);
		const occurredAt = optionalText(item.occurredAt, `activity.evidence[${index}].occurredAt`);
		const context = optionalText(item.provenance.context, `activity.evidence[${index}].provenance.context`);

		const reference = {
			key: evidenceKey(sourceId, id),
			sourceId,
			sourceLabel,
			evidenceId: id,
			summary: shortText(summary),
			outcome,
			provenance: { pointer, availability, ...(context ? { context } : {}) },
			...(occurredAt ? { occurredAt } : {}),
		};
		evidence.set(id, reference);
	}
	return { sourceId, evidence };
}

function normalizeRelatedEvidence(items) {
	if (items === undefined) return new Map();
	if (!Array.isArray(items)) throw new TypeError("relatedEvidence must be an array");
	const related = new Map();
	for (const [index, item] of items.entries()) {
		if (!isObject(item)) throw new TypeError(`relatedEvidence[${index}] must be an object`);
		const id = requiredText(item.id, `relatedEvidence[${index}].id`);
		if (related.has(id)) continue;
		const analogue = {
			id,
			sourceLabel: requiredText(item.sourceLabel, `relatedEvidence[${index}].sourceLabel`),
			summary: shortText(requiredText(item.summary, `relatedEvidence[${index}].summary`)),
			classification: "possible-analogue",
			verifiedOccurrence: false,
		};
		const sourcePointer = optionalText(item.sourcePointer, `relatedEvidence[${index}].sourcePointer`);
		if (sourcePointer) analogue.sourcePointer = sourcePointer;
		related.set(id, analogue);
	}
	return related;
}

function proposalIdentity(sourceId, type, observation, recommendation) {
	return JSON.stringify([
		sourceId,
		type,
		observation.toLowerCase().replace(/\s+/g, " "),
		recommendation.toLowerCase().replace(/\s+/g, " "),
	]);
}

function presentationIdentity(sourceId, type, observation, recommendation) {
	const normalize = (text) => text.toLowerCase().replace(/\s+/g, " ").trim().replace(/[.!?]+$/u, "");
	return JSON.stringify([sourceId, type, normalize(observation), normalize(recommendation)]);
}

// Stable compact 64-bit FNV-1a key, scoped to one source.
function stableId(identity) {
	let hash = 0xcbf29ce484222325n;
	for (let i = 0; i < identity.length; i++) {
		hash ^= BigInt(identity.charCodeAt(i));
		hash = BigInt.asUintN(64, hash * 0x100000001b3n);
	}
	return `opp-${hash.toString(16).padStart(16, "0")}`;
}

function assessEvidence(type, evidence) {
	const count = new Set(evidence.map((item) => item.key)).size;
	if (type === "improvement" && count >= 2) {
		return {
			claim: "recurring",
			distinctEvidenceCount: count,
			statement: `This workflow pattern is supported by ${count} distinct pieces of source evidence.`,
		};
	}
	if (type === "improvement") {
		return {
			claim: "prospective",
			distinctEvidenceCount: count,
			statement: "A plausible future improvement is suggested by one observed source event; recurrence is not established.",
		};
	}
	return {
		claim: "observed",
		distinctEvidenceCount: count,
		statement:
			count === 1
				? "Concrete friction was observed in one source event."
				: `Concrete friction was observed in ${count} distinct pieces of source evidence.`,
	};
}

function mergeById(existing, additions, idField) {
	const merged = [...(Array.isArray(existing) ? existing : [])];
	const seen = new Set(merged.map((item) => item?.[idField]).filter((value) => typeof value === "string"));
	for (const item of additions) {
		if (!seen.has(item[idField])) {
			merged.push(item);
			seen.add(item[idField]);
		}
	}
	return merged;
}

/**
 * Validate and merge proposals against normalized, source-neutral activity.
 * Only cited activity can support a record; related evidence is retained as
 * labelled analogy and never counts toward recurrence.
 *
 * @param {import("./index.d.mts").ReviewActivityInput} input
 * @returns {import("./index.d.mts").ReviewActivityResult}
 */
export function reviewActivity({ activity, proposals = [], records = [], relatedEvidence = [] }) {
	const normalized = normalizeActivity(activity);
	const related = normalizeRelatedEvidence(relatedEvidence);
	if (!Array.isArray(proposals)) throw new TypeError("proposals must be an array");
	if (!Array.isArray(records)) throw new TypeError("records must be an array");

	const currentByIdentity = new Map();
	const currentByPresentation = new Map();
	for (const record of records) {
		if (!isObject(record) || typeof record.proposalKey !== "string" || typeof record.observation !== "string") continue;
		if (!Array.isArray(record.evidence) || !record.evidence.length ||
			record.evidence.some((item) => item?.sourceId !== normalized.sourceId)) continue;
		if (!currentByIdentity.has(record.proposalKey)) currentByIdentity.set(record.proposalKey, record);
		const presentation = presentationIdentity(normalized.sourceId, record.type, record.observation, record.recommendation ?? "");
		const prior = currentByPresentation.get(presentation);
		if (!prior || (record.status === "dismissed" && prior.status !== "dismissed")) currentByPresentation.set(presentation, record);
	}

	const changedByPresentation = new Map();
	const suppressed = [];
	const rejected = [];
	for (const [index, rawProposal] of proposals.entries()) {
		if (!isObject(rawProposal)) {
			rejected.push({ proposalIndex: index, reason: "proposal must be an object" });
			continue;
		}
		const type = rawProposal.type;
		const observation = typeof rawProposal.observation === "string" ? rawProposal.observation.trim() : "";
		const recommendation = typeof rawProposal.recommendation === "string" ? rawProposal.recommendation.trim() : "";
		if (type !== "friction" && type !== "improvement") {
			rejected.push({ proposalIndex: index, reason: "type must be friction or improvement" });
			continue;
		}
		if (!observation || (type === "improvement" && !recommendation)) {
			rejected.push({ proposalIndex: index, reason: "proposal needs an observation and improvements need a recommendation" });
			continue;
		}
		if (!Array.isArray(rawProposal.evidenceIds) || rawProposal.evidenceIds.length === 0) {
			rejected.push({ proposalIndex: index, reason: "proposal must cite at least one activity evidence id" });
			continue;
		}

		const cited = [];
		let missingEvidence = false;
		for (const id of rawProposal.evidenceIds) {
			if (typeof id !== "string" || !normalized.evidence.has(id)) {
				missingEvidence = true;
				break;
			}
			const item = normalized.evidence.get(id);
			if (!cited.some((existing) => existing.key === item.key)) cited.push(item);
		}
		if (missingEvidence) {
			rejected.push({ proposalIndex: index, reason: "proposal cites evidence absent from this activity" });
			continue;
		}

		const identity = proposalIdentity(normalized.sourceId, type, observation, recommendation);
		const proposalKey = stableId(identity);
		const presentation = presentationIdentity(normalized.sourceId, type, observation, recommendation);
		const current = changedByPresentation.get(presentation) ?? currentByIdentity.get(proposalKey) ?? currentByPresentation.get(presentation);
		const previousEvidence = Array.isArray(current?.evidence) ? current.evidence : [];
		const knownEvidence = new Set(previousEvidence.map((item) => item?.key).filter((key) => typeof key === "string"));
		const newEvidence = cited.filter((item) => !knownEvidence.has(item.key));
		if (current?.status === "dismissed" && newEvidence.length === 0) {
			suppressed.push({ id: current.id, proposalKey: current.proposalKey, reason: "dismissed-without-new-evidence" });
			continue;
		}
		if (current && newEvidence.length === 0) continue;

		const addedAnalogues = [];
		for (const id of Array.isArray(rawProposal.relatedEvidenceIds) ? rawProposal.relatedEvidenceIds : []) {
			if (typeof id === "string" && related.has(id)) addedAnalogues.push(related.get(id));
		}
		const evidence = mergeById(previousEvidence, newEvidence, "key");
		const reviewHistory = Array.isArray(current?.reviewHistory) ? current.reviewHistory : [];
		const dismissalHistory =
			current?.status === "dismissed" && !reviewHistory.some((event) => event?.status === "dismissed")
				? [...reviewHistory, { status: "dismissed" }]
				: reviewHistory;
		const record = current
			? {
				...current,
				evidence,
				evidenceAssessment: assessEvidence(type, evidence),
				analogues: mergeById(current.analogues, addedAnalogues, "id"),
				...(current.status === "dismissed"
					? {
						status: "open",
						reviewHistory: [...dismissalHistory, { status: "open", reason: "materially-new-evidence" }],
					}
					: {}),
			}
			: {
				id: proposalKey,
				proposalKey,
				type,
				observation,
				recommendation: recommendation || undefined,
				status: "open",
				reviewHistory: [],
				evidence,
				evidenceAssessment: assessEvidence(type, evidence),
				analogues: mergeById([], addedAnalogues, "id"),
			};
		changedByPresentation.set(presentation, record);
	}

	return { changes: [...changedByPresentation.values()], suppressed, rejected };
}

/** Add an operator keep/dismiss decision without discarding prior review history. */
export function setReviewStatus(record, status, { at } = {}) {
	if (!isObject(record)) throw new TypeError("record must be an object");
	if (status !== "kept" && status !== "dismissed") throw new TypeError("status must be kept or dismissed");
	if (record.status === status) return record;
	const event = { status };
	const timestamp = optionalText(at, "at");
	if (timestamp) event.at = timestamp;
	return {
		...record,
		status,
		reviewHistory: [...(Array.isArray(record.reviewHistory) ? record.reviewHistory : []), event],
	};
}

/**
 * Validate caller-proposed broader groupings when an operator explicitly asks
 * for cross-source review. Related evidence is attached as analogy only.
 *
 * @param {import("./index.d.mts").ReviewPatternsInput} input
 * @returns {import("./index.d.mts").ReviewPatternsResult}
 */
export function reviewPatterns({ records, proposals = [], relatedEvidence = [] }) {
	if (!Array.isArray(records)) throw new TypeError("records must be an array");
	if (!Array.isArray(proposals)) throw new TypeError("proposals must be an array");
	const byId = new Map(records.filter((record) => isObject(record) && typeof record.id === "string").map((record) => [record.id, record]));
	const related = normalizeRelatedEvidence(relatedEvidence);
	const groups = [];
	const rejected = [];

	for (const [index, proposal] of proposals.entries()) {
		if (!isObject(proposal) || typeof proposal.title !== "string" || !proposal.title.trim() || !Array.isArray(proposal.recordIds)) {
			rejected.push({ proposalIndex: index, reason: "group needs a title and record ids" });
			continue;
		}
		const recordIds = [...new Set(proposal.recordIds.filter((id) => typeof id === "string"))];
		const selected = recordIds.map((id) => byId.get(id));
		if (recordIds.length < 2 || selected.some((record) => !record)) {
			rejected.push({ proposalIndex: index, reason: "group must reference at least two known records" });
			continue;
		}
		const sources = new Map();
		for (const record of selected) {
			for (const item of Array.isArray(record.evidence) ? record.evidence : []) {
				if (typeof item?.sourceId !== "string") continue;
				if (!sources.has(item.sourceId)) {
					sources.set(item.sourceId, { sourceId: item.sourceId, sourceLabel: item.sourceLabel ?? item.sourceId });
				}
			}
		}
		if (sources.size < 2) {
			rejected.push({ proposalIndex: index, reason: "cross-source grouping needs local evidence from at least two distinct sources" });
			continue;
		}
		const analogues = [];
		for (const id of Array.isArray(proposal.relatedEvidenceIds) ? proposal.relatedEvidenceIds : []) {
			if (typeof id === "string" && related.has(id)) analogues.push(related.get(id));
		}
		groups.push({
			title: proposal.title.trim(),
			recordIds,
			sources: [...sources.values()],
			evidenceClaim: `Local records contain evidence from ${sources.size} distinct sources.`,
			possibleAnalogues: mergeById([], analogues, "id"),
		});
	}
	return { groups, rejected };
}
