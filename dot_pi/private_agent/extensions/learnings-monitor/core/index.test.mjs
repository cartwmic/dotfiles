import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { reviewActivity, reviewPatterns, setReviewStatus } from "./index.mjs";

function activity(sourceId, evidence) {
	return {
		source: { id: sourceId, label: `source ${sourceId}` },
		evidence: evidence.map(({ id, summary = `summary ${id}`, ...fields }) => ({
			id,
			summary,
			outcome: "completed",
			provenance: { pointer: `fixture://${sourceId}#${id}`, ...fields.provenance },
			...("outcome" in fields ? { outcome: fields.outcome } : {}),
		})),
	};
}

const reusableProposal = (evidenceIds) => ({
	type: "improvement",
	observation: "A repeated setup step is manual.",
	recommendation: "Consider a small reusable setup script.",
	evidenceIds,
});

test("one-off friction is recorded as observed, with failed outcome and source provenance", () => {
	const result = reviewActivity({
		activity: activity("source-a", [
			{
				id: "attempt-1",
				summary: "formatter failed because configuration was missing",
				outcome: "failed",
				provenance: { pointer: "session://one#turn-4", context: "branch:experiment", availability: "available" },
			},
		]),
		proposals: [{ type: "friction", observation: "Formatter configuration was missing.", evidenceIds: ["attempt-1"] }],
	});

	assert.equal(result.changes.length, 1);
	const [record] = result.changes;
	assert.equal(record.type, "friction");
	assert.equal(record.status, "open");
	assert.equal(record.evidenceAssessment.claim, "observed");
	assert.equal(record.evidenceAssessment.distinctEvidenceCount, 1);
	assert.equal(record.evidence[0].outcome, "failed");
	assert.deepEqual(record.evidence[0].provenance, {
		pointer: "session://one#turn-4",
		availability: "available",
		context: "branch:experiment",
	});
});

test("one-event suggestion stays prospective; distinct evidence supports a recurring claim", () => {
	const evidence = [
		{ id: "step-1", summary: "prepared report manually" },
		{ id: "step-2", summary: "prepared report manually again" },
	];
	const once = reviewActivity({ activity: activity("source-a", evidence), proposals: [reusableProposal(["step-1"])] });
	const repeated = reviewActivity({ activity: activity("source-a", evidence), proposals: [reusableProposal(["step-1", "step-2"])] });

	assert.equal(once.changes[0].evidenceAssessment.claim, "prospective");
	assert.match(once.changes[0].evidenceAssessment.statement, /recurrence is not established/);
	assert.equal(repeated.changes[0].evidenceAssessment.claim, "recurring");
	assert.equal(repeated.changes[0].evidenceAssessment.distinctEvidenceCount, 2);
	assert.match(repeated.changes[0].evidenceAssessment.statement, /2 distinct pieces of source evidence/);
});

test("empty proposal output is empty and does not invent a record", () => {
	assert.deepEqual(
		reviewActivity({ activity: activity("source-a", [{ id: "event-1" }]), proposals: [] }),
		{ changes: [], suppressed: [], rejected: [] },
	);
});

test("dismissal suppresses identical evidence and resurfaces only with new evidence", () => {
	const firstActivity = activity("source-a", [{ id: "step-1", summary: "manual setup" }]);
	const first = reviewActivity({ activity: firstActivity, proposals: [reusableProposal(["step-1"])] }).changes[0];
	const dismissed = setReviewStatus(first, "dismissed", { at: "2030-01-01T00:00:00Z" });

	const repeat = reviewActivity({ activity: firstActivity, proposals: [reusableProposal(["step-1"])], records: [dismissed] });
	assert.equal(repeat.changes.length, 0);
	assert.equal(repeat.suppressed[0].reason, "dismissed-without-new-evidence");

	const later = reviewActivity({
		activity: activity("source-a", [{ id: "step-2", summary: "manual setup happened again" }]),
		proposals: [reusableProposal(["step-2"])],
		records: [dismissed],
	});
	assert.equal(later.changes.length, 1);
	assert.equal(later.changes[0].status, "open");
	assert.deepEqual(later.changes[0].reviewHistory, [
		{ status: "dismissed", at: "2030-01-01T00:00:00Z" },
		{ status: "open", reason: "materially-new-evidence" },
	]);
	assert.equal(later.changes[0].evidenceAssessment.claim, "recurring");
	assert.equal(later.changes[0].evidenceAssessment.distinctEvidenceCount, 2);
});

test("cosmetic punctuation cannot reopen dismissed advice with the same evidence", () => {
	const observed = activity("source-a", [{ id: "step-1" }]);
	const original = reviewActivity({ activity: observed, proposals: [reusableProposal(["step-1"])] }).changes[0];
	const dismissed = setReviewStatus(original, "dismissed");
	const cosmetic = reviewActivity({
		activity: observed,
		proposals: [{
			...reusableProposal(["step-1"]),
			observation: "A repeated setup step is manual!",
			recommendation: "Consider a small reusable setup script!",
		}],
		records: [dismissed],
	});

	assert.deepEqual(cosmetic.changes, []);
	assert.equal(cosmetic.suppressed.length, 1);
	assert.equal(cosmetic.suppressed[0].id, dismissed.id);
	assert.equal(dismissed.status, "dismissed");
});

test("cosmetic aliases never reuse a record from another source", () => {
	const fromA = reviewActivity({
		activity: activity("source-a", [{ id: "step-1" }]),
		proposals: [reusableProposal(["step-1"])],
	}).changes[0];
	for (const existing of [fromA, setReviewStatus(fromA, "dismissed")]) {
		const fromB = reviewActivity({
			activity: activity("source-b", [{ id: "step-1" }]),
			proposals: [{ ...reusableProposal(["step-1"]), observation: "A repeated setup step is manual!" }],
			records: [existing],
		});
		assert.equal(fromB.changes.length, 1);
		assert.equal(fromB.suppressed.length, 0);
		assert.notEqual(fromB.changes[0].id, existing.id);
		assert.deepEqual(fromB.changes[0].evidence.map((item) => item.sourceId), ["source-b"]);
		assert.equal(fromB.changes[0].evidenceAssessment.claim, "prospective");
		assert.equal(fromB.changes[0].status, "open");
	}
});

test("a different intervention on the same evidence gets a separate proposal", () => {
	const observed = activity("source-a", [{ id: "step-1" }]);
	const original = reviewActivity({ activity: observed, proposals: [reusableProposal(["step-1"])] }).changes[0];
	const dismissed = setReviewStatus(original, "dismissed");
	const different = reviewActivity({
		activity: observed,
		proposals: [{ ...reusableProposal(["step-1"]), recommendation: "Consider a reusable checklist instead." }],
		records: [dismissed],
	});

	assert.equal(different.changes.length, 1);
	assert.notEqual(different.changes[0].id, dismissed.id);
	assert.equal(different.changes[0].status, "open");
	assert.equal(dismissed.status, "dismissed");
});

test("related evidence stays a labelled analogue and cannot establish recurrence", () => {
	const result = reviewActivity({
		activity: activity("source-a", [{ id: "step-1" }]),
		proposals: [{ ...reusableProposal(["step-1"]), relatedEvidenceIds: ["memory-1"] }],
		relatedEvidence: [{ id: "memory-1", sourceLabel: "another project", summary: "A similar workflow was mentioned." }],
	});
	const record = result.changes[0];
	assert.equal(record.evidenceAssessment.claim, "prospective");
	assert.equal(record.evidence.length, 1);
	assert.equal(record.analogues[0].classification, "possible-analogue");
	assert.equal(record.analogues[0].verifiedOccurrence, false);
});

test("cross-source review requires distinct local sources; analogues do not count", () => {
	const sourceA = reviewActivity({
		activity: activity("source-a", [{ id: "a1" }]),
		proposals: [{ type: "friction", observation: "same issue", evidenceIds: ["a1"] }],
	}).changes[0];
	const sourceB = reviewActivity({
		activity: activity("source-b", [{ id: "b1" }]),
		proposals: [{ type: "friction", observation: "same issue", evidenceIds: ["b1"] }],
	}).changes[0];
	const sameSource = reviewPatterns({
		records: [sourceA],
		proposals: [{ title: "A broad workflow pattern", recordIds: [sourceA.id, sourceA.id] }],
	});
	assert.equal(sameSource.groups.length, 0);

	const crossSource = reviewPatterns({
		records: [sourceA, sourceB],
		proposals: [{ title: "A broad workflow pattern", recordIds: [sourceA.id, sourceB.id], relatedEvidenceIds: ["memory-1"] }],
		relatedEvidence: [{ id: "memory-1", sourceLabel: "other project", summary: "Similar issue there." }],
	});
	assert.equal(crossSource.groups.length, 1);
	assert.equal(crossSource.groups[0].sources.length, 2);
	assert.equal(crossSource.groups[0].possibleAnalogues[0].verifiedOccurrence, false);
});

test("portable fixture runs in a separate non-Pi process through the core operation", () => {
	const fixturePath = fileURLToPath(new URL("./portable-fixture.mjs", import.meta.url));
	const run = spawnSync(process.execPath, [fixturePath], { encoding: "utf8" });
	assert.equal(run.status, 0, run.stderr);
	const result = JSON.parse(run.stdout);
	assert.equal(result.changes.length, 3);
	const friction = result.changes.find((record) => record.type === "friction");
	const improvements = result.changes.filter((record) => record.type === "improvement");
	const prospective = improvements.find((record) => record.evidenceAssessment.claim === "prospective");
	const recurring = improvements.find((record) => record.evidenceAssessment.claim === "recurring");
	assert.equal(friction.status, "open");
	assert.match(friction.observation, /formatter could not run/);
	assert.equal(friction.evidence[0].outcome, "failed");
	assert.equal(prospective.status, "open");
	assert.match(prospective.observation, /one-time log cleanup/);
	assert.equal(recurring.status, "open");
	assert.equal(recurring.evidenceAssessment.distinctEvidenceCount, 2);
});
