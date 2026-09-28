import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
	defaultSpawnEditor,
	readConfiguredEditor,
	resolveEditorCommand,
} from "../inspect-prompt/helpers.ts";

export type EditorResult =
	| { kind: "saved"; text: string }
	| { kind: "cancelled"; code: number | null }
	| { kind: "failed"; error: unknown };

type EditorContext = Pick<ExtensionContext, "mode" | "hasUI" | "cwd" | "ui">;

export type EditorDependencies = {
	resolveCommand?: (ctx: EditorContext) => string;
	spawnEditor?: (command: string, filePath: string) => Promise<number | null>;
	makeTempDir?: (prefix: string) => string;
	writeFile?: (path: string, content: string, options: { encoding: "utf8"; mode: number }) => void;
	readFile?: (path: string) => string;
	remove?: (path: string) => void;
	clearTerminal?: () => void;
};

export async function runExternalReminderEditor(
	ctx: EditorContext,
	initialText: string,
	deps: EditorDependencies = {},
): Promise<EditorResult> {
	if (!ctx.hasUI || ctx.mode !== "tui" || typeof ctx.ui.custom !== "function") {
		return { kind: "failed", error: new Error("The external reminder editor is available only in Pi's terminal UI.") };
	}

	const resolveCommand = deps.resolveCommand ?? ((context) =>
		resolveEditorCommand({ configuredEditor: readConfiguredEditor({ cwd: context.cwd }) }));
	const spawnEditor = deps.spawnEditor ?? defaultSpawnEditor;
	const makeTempDir = deps.makeTempDir ?? ((prefix) => mkdtempSync(join(tmpdir(), prefix)));
	const writeFile = deps.writeFile ?? ((path, content, options) => writeFileSync(path, content, options));
	const readFile = deps.readFile ?? ((path) => readFileSync(path, "utf8"));
	const remove = deps.remove ?? ((path) => rmSync(path, { recursive: true, force: true }));
	const clearTerminal = deps.clearTerminal ?? (() => process.stdout.write("\x1b[2J\x1b[H"));
	const command = resolveCommand(ctx);
	let result: EditorResult = { kind: "failed", error: new Error("Editor did not complete") };

	try {
		await ctx.ui.custom((tui, _theme, _keybindings, done) => {
			let finished = false;
			let directory: string | undefined;
			const finish = (value: EditorResult) => {
				if (finished) return;
				finished = true;
				result = value;
				if (directory) {
					try {
						remove(directory);
					} catch {
						// Best-effort cleanup; never replace the editor outcome.
					}
				}
				try {
					tui.start();
					tui.requestRender?.(true);
				} catch {
					// Pi will still complete the UI prompt and report the editor result.
				}
				done(value);
			};

			try {
				tui.stop();
				clearTerminal();
				directory = makeTempDir("pi-standing-reminder-");
				const draftPath = join(directory, "reminder.txt");
				writeFile(draftPath, initialText, { encoding: "utf8", mode: 0o600 });
				void spawnEditor(command, draftPath).then((code) => {
					if (code !== 0) {
						finish({ kind: "cancelled", code });
						return;
					}
					try {
						finish({ kind: "saved", text: readFile(draftPath) });
					} catch (error) {
						finish({ kind: "failed", error });
					}
				}, (error: unknown) => finish({ kind: "failed", error }));
			} catch (error) {
				finish({ kind: "failed", error });
			}
			return { render: () => [] };
		});
	} catch (error) {
		return { kind: "failed", error };
	}
	return result;
}
