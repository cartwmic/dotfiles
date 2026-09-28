export type ActivityOutcome = "completed" | "failed" | "incomplete" | "unknown";
export type SourceAvailability = "available" | "unavailable" | "unknown";
export type OpportunityType = "friction" | "improvement";
export type ReviewStatus = "open" | "kept" | "dismissed";
export type EvidenceClaim = "observed" | "prospective" | "recurring";

/** Opaque origin pointer plus optional source-specific context such as a branch. */
export interface Provenance {
	pointer: string;
	availability?: SourceAvailability;
	context?: string;
}

export interface ActivityEvidence {
	id: string;
	summary: string;
	outcome?: ActivityOutcome;
	occurredAt?: string;
	provenance: Provenance;
}

/** Stable identifier for one producer/source; its format has no core meaning. */
export interface ActivitySource {
	id: string;
	label?: string;
}

export interface Activity {
	source: ActivitySource;
	evidence: ActivityEvidence[];
}

/** A proposal can cite only evidence IDs in the accompanying Activity. */
export interface OpportunityProposal {
	type: OpportunityType;
	observation: string;
	recommendation?: string;
	evidenceIds: string[];
	relatedEvidenceIds?: string[];
}

/** Context retrieved elsewhere; it is always represented as an analogue, not an occurrence. */
export interface RelatedEvidence {
	id: string;
	sourceLabel: string;
	summary: string;
	sourcePointer?: string;
}

export interface EvidenceReference {
	key: string;
	sourceId: string;
	sourceLabel: string;
	evidenceId: string;
	summary: string;
	outcome: ActivityOutcome;
	provenance: Provenance & { availability: SourceAvailability };
	occurredAt?: string;
}

export interface ReviewHistoryEntry {
	status: ReviewStatus;
	at?: string;
	reason?: string;
}

export interface EvidenceAssessment {
	claim: EvidenceClaim;
	distinctEvidenceCount: number;
	statement: string;
}

export interface OpportunityRecord {
	id: string;
	/** Stable opaque match key. Do not use as a file path. */
	proposalKey: string;
	type: OpportunityType;
	observation: string;
	recommendation?: string;
	status: ReviewStatus;
	reviewHistory: ReviewHistoryEntry[];
	evidence: EvidenceReference[];
	evidenceAssessment: EvidenceAssessment;
	analogues: Array<RelatedEvidence & { classification: "possible-analogue"; verifiedOccurrence: false }>;
}

export interface ReviewActivityInput {
	activity: Activity;
	proposals?: OpportunityProposal[];
	records?: OpportunityRecord[];
	relatedEvidence?: RelatedEvidence[];
}

export interface ReviewActivityResult {
	/** New or changed records only; persist these without replacing untouched owner-edited records. */
	changes: OpportunityRecord[];
	suppressed: Array<{ id: string; proposalKey: string; reason: "dismissed-without-new-evidence" }>;
	rejected: Array<{ proposalIndex: number; reason: string }>;
}

export interface PatternProposal {
	title: string;
	recordIds: string[];
	relatedEvidenceIds?: string[];
}

export interface ReviewedPattern {
	title: string;
	recordIds: string[];
	sources: Array<{ sourceId: string; sourceLabel: string }>;
	evidenceClaim: string;
	possibleAnalogues: OpportunityRecord["analogues"];
}

export interface ReviewPatternsInput {
	records: OpportunityRecord[];
	proposals?: PatternProposal[];
	relatedEvidence?: RelatedEvidence[];
}

export interface ReviewPatternsResult {
	groups: ReviewedPattern[];
	rejected: Array<{ proposalIndex: number; reason: string }>;
}

/** Pure opportunity validation/merge. No files, Pi APIs, or memory clients are accessed. */
export function reviewActivity(input: ReviewActivityInput): ReviewActivityResult;

/** Immutable keep/dismiss transition; existing review history is retained. */
export function setReviewStatus(
	record: OpportunityRecord,
	status: Exclude<ReviewStatus, "open">,
	options?: { at?: string },
): OpportunityRecord;

/** On-demand grouping; every accepted group needs local evidence from at least two sources. */
export function reviewPatterns(input: ReviewPatternsInput): ReviewPatternsResult;
