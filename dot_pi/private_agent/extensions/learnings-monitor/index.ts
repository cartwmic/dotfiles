import { join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import * as sdk from "@earendil-works/pi-coding-agent";
import { Text, ScrollView, matchesKey, truncateToWidth, wrapTextWithAnsi } from "@earendil-works/pi-tui";
import { loadConfig as loadHindsightConfig } from "../hindsight/config.ts";
import { createHindsightMemoryAdapter } from "./memory.mjs";
import { createLearningStore } from "./store.mjs";
import { createPiObserverRunner } from "./worker.mjs";
import { registerLearningsReviewCommands } from "./review.mjs";
import { createLearningsMonitorRuntime } from "./runtime.mjs";

function createMemoryAdapter(agentDir: string) {
	try {
		const config = loadHindsightConfig(join(agentDir, "extensions", "hindsight"));
		const profile = config.bankId === "work"
			? "axon-work-computer"
			: config.bankId === "cartwmic"
				? "personal"
				: undefined;
		if (!profile) return null;
		return createHindsightMemoryAdapter({
			profile,
			apiUrl: config.apiUrl,
			apiToken: config.apiToken,
			recallTypes: config.recallTypes,
			recallBudget: config.recallBudget,
			recallMaxTokens: config.recallMaxTokens,
			// Related-memory lookup runs only during detached observation or explicit cross-source review.
			requestTimeoutMs: config.requestTimeoutMs,
		});
	} catch {
		return null;
	}
}

/**
 * Primary-session Learnings monitor. T7 can register review commands through
 * createLearningsMonitorRuntime's `registerReviewCommands` surface without
 * changing this extension's capture, worker, or control lifecycle.
 */
export default function (pi: ExtensionAPI): void {
	const agentDir = sdk.getAgentDir();
	const store = createLearningStore();
	const memory = createMemoryAdapter(agentDir);
	createLearningsMonitorRuntime(pi, {
		store,
		memory,
		createWorker: (tools) => createPiObserverRunner({
			sdk,
			store,
			agentDir,
			tools,
		}),
		registerReviewCommands: (extension, review) => registerLearningsReviewCommands(extension, review, sdk, { Text, ScrollView, matchesKey, truncateToWidth, wrapTextWithAnsi }),
	});
}

export { createLearningsMonitorRuntime, parseProposals } from "./runtime.mjs";
export type { LearningsReviewSurface, LearningsMonitorRuntimeOptions } from "./runtime.d.mts";
export { createLearningsMonitorControls, DEFAULT_OBSERVER_TOOLS } from "./control.mjs";
