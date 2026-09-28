import type { ScheduledActivityBatch } from "./capture.d.mts";

export const OBSERVER_SESSION_MARKER: "learnings-monitor-observer";

export interface ObserverModelRef {
	provider: string;
	id: string;
}

export interface ObserverNativeStats {
	sessionFile: string | undefined;
	sessionId: string;
	userMessages: number;
	assistantMessages: number;
	toolCalls: number;
	toolResults: number;
	totalMessages: number;
	tokens: {
		input: number;
		output: number;
		cacheRead: number;
		cacheWrite: number;
		total: number;
	};
	cost: number;
}

export interface ObserverWorkerStats {
	sourceId: string;
	observerSession: boolean;
	sessionFile: string | null;
	sessionId: string | null;
	sessionName?: string | null;
	model: ObserverModelRef | null;
	running: boolean;
	tools: string[];
	providerExtensions?: string[];
	nativeStats: ObserverNativeStats | null;
	lastError: string | null;
}

export interface ObserverRunResult {
	batchId: string | null;
	text: string;
	model: ObserverModelRef;
	sessionFile: string | undefined;
	sessionId: string;
	nativeStats: ObserverNativeStats;
}

export interface PiObserverRunnerOptions {
	sdk: any;
	store: any;
	agentDir?: string;
	/** Provider ID to installed extension entry points; only the selected provider's paths load in its worker runtime. */
	providerExtensionLoadout?: Record<string, string[]>;
	/** Built-in read/search tool allowlist. `bash`, `edit`, and `write` are rejected. */
	tools?: string[];
	/** Optional alternate session directory, mainly useful for isolated tests. */
	sessionDir?: string;
	modelRuntimeFactory?: (context: { sdk: any; cwd: string; agentDir: string; sourceId: string; sessionFile?: string }) => Promise<any> | any;
	settingsManagerFactory?: (context: { sdk: any; cwd: string; agentDir: string; tools: string[] }) => Promise<any> | any;
	resourceLoaderFactory?: (context: { sdk: any; cwd: string; agentDir: string; settingsManager: any; extensionPaths: string[] }) => Promise<any> | any;
	sessionManagerFactory?: (context: { sdk: any; cwd: string; sessionFile?: string; sessionDir?: string }) => any;
	cwdForSource?: (sourceId: string) => string | undefined;
}

export class ObserverRunnerError extends Error {
	code: string;
	sourceId?: string;
	model?: string;
	sessionFile?: string;
}

export function getDefaultProviderExtensionLoadout(agentDir: string): Record<string, string[]>;
export function createPiObserverRunner(options: PiObserverRunnerOptions): {
	run(batch: ScheduledActivityBatch): Promise<ObserverRunResult>;
	resume(sourceId: string, options?: { cwd?: string; model?: string | ObserverModelRef }): Promise<({ ok: true } & ObserverWorkerStats) | { ok: false; reason: "no-worker" | "worker-session-missing"; sourceId: string; sessionFile?: string }>;
	selectModel(sourceId: string, model: string | ObserverModelRef): Promise<({ ok: true } & ObserverWorkerStats) | { ok: false; reason: "no-worker"; sourceId: string}>;
	abort(sourceId: string): Promise<{ ok: true; aborted: boolean } & ObserverWorkerStats>;
	stats(sourceId: string): Promise<ObserverWorkerStats & { available?: boolean; pending: number }>;
	dispose(sourceId: string): Promise<void>;
	close(): Promise<void>;
};
