import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import type { ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import type { LearningsReviewSurface } from "./runtime.d.mts";

export interface LearningsReviewCommands {
	review(args: string, ctx: ExtensionCommandContext): Promise<string>;
	setStatus(args: string, status: "kept" | "dismissed", ctx?: ExtensionCommandContext): Promise<string>;
	promote(args: string, ctx: ExtensionCommandContext): Promise<string>;
	cleanup(args: string, ctx: ExtensionCommandContext): Promise<string>;
}

export function createLearningsReviewCommands(surface: LearningsReviewSurface, sdk?: unknown): LearningsReviewCommands;
export function registerLearningsReviewCommands(pi: ExtensionAPI, surface: LearningsReviewSurface, sdk?: unknown): LearningsReviewCommands;
