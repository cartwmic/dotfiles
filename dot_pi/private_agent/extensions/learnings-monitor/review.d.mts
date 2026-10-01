import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import type { ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import type { LearningsReviewSurface } from "./runtime.d.mts";

import type { SourceSummary, StoredOpportunityRecord } from "./store.d.mts";

export interface ReviewIdentity { sourceId: string; id: string }
export interface ReviewRow extends ReviewIdentity {
	source: Pick<SourceSummary, "sourceId" | "label" | "path">;
	record: StoredOpportunityRecord;
	path: string;
	detail: string;
}
export interface ReviewChoice extends ReviewIdentity { status?: "kept" | "dismissed"; promote: boolean }
export interface ReviewDraft {
	readonly size: number;
	entries(): ReviewChoice[];
	get(identity: ReviewIdentity): ReviewChoice | undefined;
	stage(identity: ReviewIdentity, status: "kept" | "dismissed"): void;
	togglePromotion(row: ReviewIdentity & { record: StoredOpportunityRecord }): boolean;
	reset(identity: ReviewIdentity): boolean;
	clear(): void;
}
export type ReviewScope = "current" | "all" | { sourceId: string };
export interface ReviewQuery {
	scope: ReviewScope;
	status: "open" | "kept" | "dismissed" | "all";
	sources: SourceSummary[];
	rows: ReviewRow[];
	root: string;
}
export interface ReviewApplyResult {
	applied: (ReviewIdentity & { record: StoredOpportunityRecord })[];
	errors: (ReviewIdentity & { error: string })[];
	promotions: (ReviewIdentity & { message: string })[];
	remaining: ReviewChoice[];
}
export function reviewIdentityKey(identity: ReviewIdentity): string;
export function createReviewDraft(): ReviewDraft;

export interface LearningsReviewCommands {
	createDraft(): ReviewDraft;
	query(options?: { scope?: ReviewScope; status?: ReviewQuery["status"] }, ctx?: ExtensionCommandContext): Promise<ReviewQuery>;
	apply(draft: ReviewDraft, ctx?: ExtensionCommandContext): Promise<ReviewApplyResult>;
	promoteRecord(identity: ReviewIdentity, ctx?: ExtensionCommandContext): Promise<string>;
	review(args: string, ctx: ExtensionCommandContext): Promise<string>;
	setStatus(args: string, status: "kept" | "dismissed", ctx?: ExtensionCommandContext): Promise<string>;
	promote(args: string, ctx: ExtensionCommandContext): Promise<string>;
	cleanup(args: string, ctx: ExtensionCommandContext): Promise<string>;
}

export function createLearningsReviewCommands(surface: LearningsReviewSurface, sdk?: unknown): LearningsReviewCommands;
export function registerLearningsReviewCommands(pi: ExtensionAPI, surface: LearningsReviewSurface, sdk?: unknown, uiDeps?: import("./review-ui.mjs").ReviewUIDependencies): LearningsReviewCommands;
