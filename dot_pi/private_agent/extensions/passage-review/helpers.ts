import { spawn } from "node:child_process";
import type { ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import type { SessionEntry } from "@earendil-works/pi-coding-agent";

export type PassageReviewContext = Pick<
	ExtensionCommandContext,
	"mode" | "hasUI" | "cwd" | "isIdle" | "sessionManager" | "ui"
>;

export type SpawnReview = (command: string, args: string[], source: string) => Promise<number | null>;
export type PauseTui = (ctx: PassageReviewContext, action: () => Promise<void>) => Promise<void>;

export type PassageReviewDependencies = {
	command?: () => string;
	spawnReview?: SpawnReview;
	pauseTui?: PauseTui;
};

export function latestAssistantReply(entries: readonly SessionEntry[]): string | undefined {
	for (let index = entries.length - 1; index >= 0; index -= 1) {
		const entry = entries[index];
		if (entry.type !== "message" || entry.message.role !== "assistant") continue;
		const content = entry.message.content;
		const text = typeof content === "string"
			? content
			: Array.isArray(content)
				? content.filter((part) => part.type === "text").map((part) => part.text).join("\n")
				: "";
		if (text.trim()) return text;
	}
	return undefined;
}

export function resolvePassageReviewCommand(env: NodeJS.ProcessEnv = process.env): string {
	return env.PASSAGE_REVIEW_BIN?.trim() || "passage-review";
}

export async function spawnPassageReview(
	command: string,
	args: string[],
	source: string,
): Promise<number | null> {
	return await new Promise((resolve, reject) => {
		let settled = false;
		const finish = (code: number | null) => {
			if (settled) return;
			settled = true;
			resolve(code);
		};
		try {
			const child = spawn(command, args, { stdio: ["pipe", "inherit", "inherit"] });
			child.once("error", (error) => {
				if (settled) return;
				settled = true;
				reject(error);
			});
			child.once("close", (code) => finish(code));
			child.stdin?.on("error", () => {});
			child.stdin?.end(source);
		} catch (error) {
			reject(error);
		}
	});
}

export async function defaultPauseTui(ctx: PassageReviewContext, action: () => Promise<void>): Promise<void> {
	if (ctx.mode !== "tui") {
		await action();
		return;
	}
	await ctx.ui.custom(async (tui, _theme, _keybindings, done) => {
		tui.stop();
		try {
			await action();
		} finally {
			tui.start();
			done(undefined);
		}
		return { render: () => [] };
	});
}

export async function runPassageReview(
	ctx: PassageReviewContext,
	dependencies: PassageReviewDependencies = {},
): Promise<void> {
	if (!ctx.hasUI || ctx.mode !== "tui") {
		if (ctx.hasUI) ctx.ui.notify("/review needs Pi's interactive terminal; use passage-review directly otherwise.", "info");
		return;
	}
	if (!ctx.isIdle()) {
		ctx.ui.notify("/review is available when the agent is idle.", "info");
		return;
	}

	const reply = latestAssistantReply(ctx.sessionManager.getBranch());
	if (!reply) {
		ctx.ui.notify("No assistant reply with text is available to review.", "warning");
		return;
	}

	const title = `Pi reply — session ${ctx.sessionManager.getSessionId()}`;
	const command = (dependencies.command ?? (() => resolvePassageReviewCommand()))();
	const spawnReview = dependencies.spawnReview ?? spawnPassageReview;
	const pauseTui = dependencies.pauseTui ?? defaultPauseTui;
	try {
		let exitCode: number | null = null;
		await pauseTui(ctx, async () => {
			exitCode = await spawnReview(command, ["new", "--title", title], reply);
		});
		if (exitCode === 0) ctx.ui.notify("Opened the latest assistant reply in passage-review.", "info");
		else ctx.ui.notify(`passage-review exited with status ${exitCode ?? "unknown"}.`, "error");
	} catch (error) {
		ctx.ui.notify(`Could not start passage-review: ${error instanceof Error ? error.message : String(error)}`, "error");
	}
}
