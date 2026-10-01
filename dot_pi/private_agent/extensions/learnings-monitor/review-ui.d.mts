import type { ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import type { LearningsReviewCommands } from "./review.mjs";
export interface ReviewUIDependencies {
 Text: any; ScrollView: any;
 matchesKey(data: string, key: any): boolean;
 truncateToWidth(text: string, width: number): string;
 wrapTextWithAnsi(text: string, width: number): string[];
}
export function recordedTime(value?: string, now?: number): string;
export function createReviewView(options: any): { render(width: number): string[]; handleInput(data: string): void; invalidate(): void };
export function openReview(commands: LearningsReviewCommands, ctx: ExtensionCommandContext, deps?: ReviewUIDependencies): Promise<void>;
