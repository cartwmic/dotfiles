import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join } from "node:path";

export type EditorResolutionInput = {
	configuredEditor?: string | null;
	env?: NodeJS.Dict<string>;
	platform?: NodeJS.Platform;
};

export function resolveEditorCommand(input: EditorResolutionInput = {}): string {
	const configured = input.configuredEditor?.trim();
	if (configured) return configured;
	const env = input.env ?? process.env;
	const environmentEditor = env.VISUAL || env.EDITOR;
	if (environmentEditor) return environmentEditor;
	const platform = input.platform ?? process.platform;
	return platform === "win32" ? "notepad" : "nano";
}

export function shouldOpenEditor(opts: { hasUI: boolean; idle: boolean }): boolean {
	return opts.hasUI && opts.idle;
}

export type SettingsReader = {
	existsSync: (path: string) => boolean;
	readFileSync: (path: string, encoding: "utf-8") => string;
};

function readExternalEditorField(
	path: string,
	io: SettingsReader,
): { present: boolean; value: unknown } {
	if (!io.existsSync(path)) return { present: false, value: undefined };
	try {
		const parsed = JSON.parse(io.readFileSync(path, "utf-8")) as {
			externalEditor?: unknown;
		};
		if (parsed && typeof parsed === "object" && "externalEditor" in parsed) {
			return { present: true, value: parsed.externalEditor };
		}
	} catch {
		return { present: false, value: undefined };
	}
	return { present: false, value: undefined };
}

export function defaultAgentDir(env: NodeJS.Dict<string> = process.env): string {
	const override = env.PI_CODING_AGENT_DIR;
	if (typeof override === "string" && override.trim() !== "") return override;
	return join(homedir(), ".pi", "agent");
}

export function readConfiguredEditor(opts: {
	cwd: string;
	agentDir?: string;
	io?: SettingsReader;
}): string | undefined {
	const io = opts.io ?? {
		existsSync,
		readFileSync: (path, encoding) => readFileSync(path, encoding),
	};
	const agentDir = opts.agentDir ?? defaultAgentDir();
	const project = readExternalEditorField(join(opts.cwd, ".pi", "settings.json"), io);
	const global = readExternalEditorField(join(agentDir, "settings.json"), io);
	const raw = project.present ? project.value : global.present ? global.value : undefined;
	return typeof raw === "string" ? raw : undefined;
}

export type InspectPromptContext = {
	hasUI: boolean;
	mode?: string;
	cwd: string;
	isIdle: () => boolean;
	getSystemPrompt: () => string;
	ui: {
		notify: (message: string, type?: "info" | "warning" | "error") => void;
		custom?: (
			factory: (
				tui: { stop: () => void; start: () => void },
				theme: unknown,
				keybindings: unknown,
				done: (result: unknown) => void,
			) => unknown | Promise<unknown>,
		) => Promise<unknown>;
	};
};

export type InspectPromptDeps = {
	resolveEditorCommand?: () => string;
	spawnEditor?: (command: string, filePath: string) => Promise<number | null>;
	pauseTui?: (fn: () => Promise<void>) => Promise<void>;
	mkdtempSync?: typeof mkdtempSync;
	writeFileSync?: typeof writeFileSync;
	rmSync?: typeof rmSync;
};

export async function defaultSpawnEditor(command: string, filePath: string): Promise<number | null> {
	const [editor, ...editorArgs] = command.split(" ");
	return await new Promise((resolve) => {
		const child = spawn(editor, [...editorArgs, filePath], {
			stdio: "inherit",
			shell: process.platform === "win32",
		});
		child.on("error", () => resolve(null));
		child.on("close", (code) => resolve(code));
	});
}

export async function defaultPauseTui(
	ctx: InspectPromptContext,
	fn: () => Promise<void>,
): Promise<void> {
	const custom = ctx.ui.custom;
	if (ctx.mode !== "tui" || typeof custom !== "function") {
		await fn();
		return;
	}
	await custom(async (tui, _theme, _keybindings, done) => {
		tui.stop();
		try {
			await fn();
		} finally {
			tui.start();
			done(undefined);
		}
		return { render: () => [] };
	});
}

export async function runInspectPrompt(
	ctx: InspectPromptContext,
	deps: InspectPromptDeps = {},
): Promise<void> {
	const idle = ctx.isIdle();
	if (!shouldOpenEditor({ hasUI: ctx.hasUI, idle })) {
		if (ctx.hasUI && !idle) {
			ctx.ui.notify("inspect-prompt is available when the agent is idle.", "info");
		}
		return;
	}

	const snapshot = ctx.getSystemPrompt();
	const command = (deps.resolveEditorCommand ?? (() =>
		resolveEditorCommand({
			configuredEditor: readConfiguredEditor({ cwd: ctx.cwd }),
		})))();
	const spawnEditor = deps.spawnEditor ?? defaultSpawnEditor;
	const pauseTui = deps.pauseTui ?? ((fn) => defaultPauseTui(ctx, fn));
	const makeTemp = deps.mkdtempSync ?? mkdtempSync;
	const write = deps.writeFileSync ?? writeFileSync;
	const remove = deps.rmSync ?? rmSync;

	await pauseTui(async () => {
		const directory = makeTemp(join(tmpdir(), "pi-inspect-prompt-"));
		const filePath = join(directory, "prompt.md");
		try {
			write(filePath, snapshot, "utf-8");
			await spawnEditor(command, filePath);
		} finally {
			try {
				remove(directory, { recursive: true, force: true });
			} catch {
				// Cleanup is best effort.
			}
		}
	});

	ctx.ui.notify("Opened assembled prompt snapshot; editor changes are not applied.", "info");
}
