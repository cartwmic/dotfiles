import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import type { PiCaptureContext, PiCaptureBridge } from "./capture.d.mts";
import type { LearningStore } from "./store.d.mts";
import type { HindsightMemoryAdapter } from "./memory.d.mts";
import type { ObserverWorkerStats } from "./worker.d.mts";

export interface LearningsReviewSurface {
	readonly store: LearningStore;
	readonly memory: HindsightMemoryAdapter | null;
	sourceStatus(ctx: PiCaptureContext): ReturnType<PiCaptureBridge["status"]>;
	workerStats(sourceId: string): Promise<ObserverWorkerStats & { available?: boolean; pending: number }>;
	disposeWorker(sourceId: string): Promise<void>;
}

export interface LearningsMonitorRuntimeOptions {
	store: LearningStore;
	createWorker(tools: string[]): {
		run(batch: any): Promise<{ text: string }>;
		stats(sourceId: string): Promise<ObserverWorkerStats & { available?: boolean; pending: number }>;
		abort(sourceId: string): Promise<unknown>;
		dispose(sourceId: string): Promise<void>;
		close(): Promise<void>;
	};
	memory?: HindsightMemoryAdapter | null;
	batchThreshold?: number;
	registerReviewCommands?(pi: ExtensionAPI, surface: LearningsReviewSurface): void;
}

export interface LearningsMonitorRuntime {
	readonly capture: PiCaptureBridge;
	readonly controls: any;
	readonly review: LearningsReviewSurface;
	getWorker(sourceId: string): ReturnType<LearningsMonitorRuntimeOptions["createWorker"]>;
	close(): Promise<void>;
}

export function createLearningsMonitorRuntime(
	pi: ExtensionAPI,
	options: LearningsMonitorRuntimeOptions,
): LearningsMonitorRuntime;

export function parseProposals(text: string): any[];
