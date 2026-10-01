import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { PiCaptureBridge } from "./capture.d.mts";
import type { LearningStore } from "./store.d.mts";
import type { ObserverWorkerStats } from "./worker.d.mts";

export const DEFAULT_OBSERVER_TOOLS: readonly ["read", "grep", "find", "ls"];

export interface LearningsMonitorControlsOptions {
	capture: PiCaptureBridge;
	store: LearningStore;
	getWorker(sourceId: string): {
		stats(sourceId: string): Promise<ObserverWorkerStats & { available?: boolean; pending: number }>;
	};
	getTools?(sourceId: string): string[];
	setTools?(sourceId: string, tools: string[]): Promise<void> | void;
}

export interface LearningsMonitorControls {
	handle(args: string, ctx: ExtensionContext): Promise<string>;
	register(pi: ExtensionAPI, options?: { command?: boolean }): void;
	recordFailure(sourceId: string, channel: string, error: unknown): void;
	recordSuccess(sourceId: string, channel: string): void;
	failureFor(sourceId: string): string | null;
	warnIfFailed(ctx: ExtensionContext): Promise<void>;
}

export function createLearningsMonitorControls(options: LearningsMonitorControlsOptions): LearningsMonitorControls;
