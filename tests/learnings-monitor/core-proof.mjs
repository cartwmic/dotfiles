import assert from "node:assert/strict";
import { reviewActivity, setReviewStatus } from "../../dot_pi/private_agent/extensions/learnings-monitor/core/index.mjs";

const activity = {
	source: { id: "scripted:work-item-17", label: "non-Pi scripted producer" },
	evidence: [{
		id: "event-1",
		summary: "A verification checklist was repeated manually across two services.",
		outcome: "completed",
		provenance: { pointer: "opaque://work-item-17/event-1", context: "main" },
	}],
};
const first = reviewActivity({
	activity,
	proposals: [{
		type: "improvement",
		observation: "The verification checklist was repeated manually.",
		recommendation: "Consider a reusable verification script.",
		evidenceIds: ["event-1"],
	}],
	records: [],
});
assert.equal(first.changes.length, 1, "a grounded one-off proposal should be written");
assert.equal(first.changes[0].evidenceAssessment.claim, "prospective");
const kept = setReviewStatus(first.changes[0], "kept", { at: "proof-time" });
assert.equal(kept.status, "kept", "the same source-neutral operation must return reviewable state");
assert.equal(kept.reviewHistory.at(-1).status, "kept");

const repeatedActivity = {
	...activity,
	evidence: [{
		id: "event-2",
		summary: "The same checklist was repeated for a third service.",
		outcome: "completed",
		provenance: { pointer: "opaque://work-item-17/event-2", context: "main" },
	}],
};
const repeated = reviewActivity({
	activity: repeatedActivity,
	proposals: [{
		type: "improvement",
		observation: "The verification checklist was repeated manually.",
		recommendation: "Consider a reusable verification script.",
		evidenceIds: ["event-2"],
	}],
	records: [kept],
});
assert.equal(repeated.changes.length, 1);
assert.equal(repeated.changes[0].evidenceAssessment.claim, "recurring");
assert.deepEqual(repeated.changes[0].evidence.map((item) => item.provenance.pointer), [
	"opaque://work-item-17/event-1",
	"opaque://work-item-17/event-2",
]);

const empty = reviewActivity({ activity: repeatedActivity, proposals: [], records: repeated.changes });
assert.equal(empty.changes.length, 0, "empty model output is a valid no-op");

console.log(JSON.stringify({
	status: kept.status,
	firstClaim: first.changes[0].evidenceAssessment.claim,
	repeatedClaim: repeated.changes[0].evidenceAssessment.claim,
	provenance: repeated.changes[0].evidence.map((item) => item.provenance.pointer),
	emptyChanges: empty.changes.length,
}, null, 2));
