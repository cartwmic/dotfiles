import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { runPassageReview } from "./helpers.ts";

export default function (pi: ExtensionAPI): void {
	pi.registerCommand("review", {
		description: "Review the latest assistant reply in the standalone passage-review library",
		handler: async (_args, ctx) => {
			await runPassageReview(ctx);
		},
	});
}
