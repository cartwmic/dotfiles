import type { Activity } from "./core/index.d.mts";
import type { OperationalState, PendingBatch } from "./store.d.mts";

export const OBSERVER_SESSION_MARKER: "learnings-monitor-observer";
export const DEFAULT_BATCH_THRESHOLD: 3;
export const MAX_BATCH_EVIDENCE: 8;
export const MAX_USER_CHARS: 1200;
export const MAX_ASSISTANT_CHARS: 1600;
export const MAX_TOOL_ACTIONS: 8;
export const MAX_TOOL_EXCERPT_CHARS: 180;
export const MAX_EXCHANGE_CHARS: 4200;
export const MAX_BATCH_BYTES: 163840;

export interface PiCaptureContext {
	cwd?: string;
	model?: { provider: string; id: string };
	sessionManager: {
		getSessionId(): string;
		getSessionFile?(): string | undefined;
		isPersisted?(): boolean;
		getEntries(): any[];
		getBranch(): any[];
		getLeafId?(): string | null;
	};
}

export interface ScheduledActivityBatch {
	sourceId: string;
	cwd: string;
	batchId: string;
	pendingBatchIds: string[];
	payload: Activity;
	explicit: boolean;
	focus: string | null;
	modelOverride: string | null;
	primaryModel: { provider: string; id: string } | null;
}

export interface PiCaptureBridge {
	enable(ctx: PiCaptureContext): Promise<{ ok: boolean; reason?: "ephemeral" | "observer"; sourceId?: string; state?: OperationalState }>;
	disable(ctx: PiCaptureContext): Promise<{ ok: boolean; reason?: "ephemeral" | "observer"; sourceId?: string; state?: OperationalState }>;
	status(ctx: PiCaptureContext): Promise<{ ok: boolean; reason?: "ephemeral" | "observer"; sourceId?: string; enabled?: boolean; pendingCount?: number; pendingEvidenceCount?: number; branch?: string; state?: OperationalState }>;
	/** Request a forced detached drain; returns without waiting for worker/model completion. */
	flush(ctx: PiCaptureContext): Promise<{ ok: boolean; reason?: "ephemeral" | "observer"; sourceId?: string; scheduled?: boolean; pendingCount?: number }>;
	resume(ctx: PiCaptureContext): Promise<{ ok: boolean; reason?: "ephemeral" | "observer"; sourceId?: string; enabled?: boolean; pendingCount?: number }>;
	captureSettled(ctx: PiCaptureContext): Promise<{ ok: boolean; captured?: boolean; evidenceId?: string; pendingCount?: number; reason?: "ephemeral" | "observer" | "off" | "no-final-assistant" | "before-enable" | "already-seen" }>;
	treeChanged(ctx: PiCaptureContext): Promise<{ ok: boolean; reason?: "ephemeral" | "observer"; sourceId?: string; branch?: string }>;
	shutdown(ctx: PiCaptureContext): Promise<{ ok: boolean; reason?: "ephemeral" | "observer"; sourceId?: string; pendingCount?: number }>;
}

export function privacyFilter(value: unknown, maxLength?: number): string;
export function isObserverSession(sessionManager: PiCaptureContext["sessionManager"]): boolean;
export function piSourceId(sessionId: string): string;
export function piBranchContext(sessionManager: PiCaptureContext["sessionManager"]): string;
export function createPiCaptureBridge(options: {
	store: {
		getOperationalState(sourceId: string): Promise<OperationalState>;
		updateOperationalState(sourceId: string, patch: Partial<Pick<OperationalState, "enabled" | "cursor">>): Promise<OperationalState>;
		enqueuePending(sourceId: string, batch: PendingBatch): Promise<OperationalState>;
		completePending(sourceId: string, batchId: string): Promise<OperationalState>;
	};
	/** Resolve only after durable result acceptance; reject on failure/abort so pending work can retry. */
	scheduleBatch?: (batch: ScheduledActivityBatch) => Promise<unknown> | unknown;
	/** Cancel source-owned worker work; never pass or retain an ExtensionContext. */
	cancelWorker?: (sourceId: string) => Promise<unknown> | unknown;
	batchThreshold?: number;
	maxBatchEvidence?: number;
	now?: () => number;
	onError?: (error: unknown, sourceId: string) => void;
}): PiCaptureBridge;

export function registerPiCaptureLifecycle(pi: any, bridge: PiCaptureBridge): void;
