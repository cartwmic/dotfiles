import type { OpportunityRecord } from "./core/index.d.mts";

/** Adapter-only first record-file creation time. Missing/invalid legacy dates are unknown. */
export type StoredOpportunityRecord = OpportunityRecord & { recordedAt?: string };

export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };

export interface PendingBatch {
	id: string;
	payload: JsonValue;
	cursorAfter?: JsonValue;
}

export interface OperationalState {
	version: 1;
	sourceId: string;
	enabled: boolean;
	cursor: JsonValue;
	pending: PendingBatch[];
	focus: string | null;
	modelOverride: string | null;
	workerSession: string | null;
}

export interface SourceSummary {
	sourceId: string;
	label: string;
	path: string;
	recordCount: number;
	enabled: boolean;
	pendingCount: number;
}

export interface LearningStore {
	readonly root: string;
	getSourceDirectory(sourceId: string): string;
	listSources(): Promise<SourceSummary[]>;
	readRecords(sourceId: string): Promise<StoredOpportunityRecord[]>;
	getRecord(sourceId: string, id: string): Promise<StoredOpportunityRecord | null>;
	applyChanges(sourceId: string, changes: OpportunityRecord[], options?: { basedOn?: OpportunityRecord[]; label?: string }): Promise<StoredOpportunityRecord[]>;
	setReviewStatus(sourceId: string, id: string, status: "kept" | "dismissed", options?: { at?: string }): Promise<StoredOpportunityRecord>;
	markSourceUnavailable(sourceId: string): Promise<number>;
	getOperationalState(sourceId: string): Promise<OperationalState>;
	updateOperationalState(sourceId: string, patch: Partial<Pick<OperationalState, "enabled" | "cursor" | "focus" | "modelOverride" | "workerSession">>): Promise<OperationalState>;
	enqueuePending(sourceId: string, batch: PendingBatch): Promise<OperationalState>;
	completePending(sourceId: string, batchId: string): Promise<OperationalState>;
	cleanupSource(sourceId: string): Promise<boolean>;
}

export function defaultStoreRoot(options?: { env?: Record<string, string | undefined>; home?: string }): string;
export function createLearningStore(options?: { root?: string }): LearningStore;
