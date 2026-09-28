import type { OpportunityRecord, RelatedEvidence } from "./core/index.d.mts";

type Profile = "personal" | "axon-work-computer";
type LookupFailureKind = "timeout" | "http-error" | "request-error" | "invalid-response";

export interface RelatedMemory extends RelatedEvidence {
	classification: "possible-analogue";
	verifiedOccurrence: false;
}

export type RelatedResult =
	| { status: "found"; evidence: RelatedMemory[] }
	| { status: "empty"; evidence: [] }
	| { status: "failed"; evidence: []; error: { kind: LookupFailureKind } };

export interface PromotionPreview {
	readonly text: string;
	readonly bankId: string;
	readonly sourceLabel: string;
}

declare const confirmedPromotion: unique symbol;
export interface ConfirmedPromotion {
	readonly [confirmedPromotion]: true;
}

export type PromotionResult =
	| { status: "accepted"; bankId: string; message: string }
	| { status: "cancelled" }
	| { status: "rejected"; reason: "not-confirmed" }
	| { status: "failed"; error: { kind: "timeout" | "http-error" | "request-error" } };

export interface HindsightMemoryAdapterOptions {
	profile: Profile;
	bankIds?: Partial<Record<Profile, string>>;
	apiUrl?: string;
	apiToken?: string;
	requestTimeoutMs?: number;
	maxQueryChars?: number;
	maxResults?: number;
	recallTypes?: string[];
	recallBudget?: "low" | "mid" | "high";
	recallMaxTokens?: number;
}

export interface HindsightMemoryAdapter {
	readonly profile: Profile;
	readonly bankId: string;
	related(query: string): Promise<RelatedResult>;
	previewPromotion(record: Pick<OpportunityRecord, "status" | "observation" | "recommendation">, exactText?: string): PromotionPreview;
	confirmPromotion(preview: PromotionPreview, confirmed: boolean): ConfirmedPromotion | null;
	retainConfirmed(payload: ConfirmedPromotion | null): Promise<PromotionResult>;
}

export function resolveMemoryBank(profile: Profile, bankIds?: Partial<Record<Profile, string>>): string;
export function createHindsightMemoryAdapter(options: HindsightMemoryAdapterOptions): HindsightMemoryAdapter;
