/**
 * inspect-prompt — open Pi's currently assembled system prompt in the
 * operator's external editor as a discarded snapshot.
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { runInspectPrompt } from "./helpers.ts";

export default function (pi: ExtensionAPI): void {
	pi.registerCommand("inspect-prompt", {
		description: "Open the assembled system prompt in your external editor (snapshot; edits are discarded)",
		handler: async (_args, ctx) => {
			await runInspectPrompt(ctx);
		},
	});
}

export { readConfiguredEditor, resolveEditorCommand, runInspectPrompt, shouldOpenEditor } from "./helpers.ts";
