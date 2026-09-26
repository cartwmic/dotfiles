import { randomUUID } from "node:crypto";
import { spawn } from "node:child_process";
import net from "node:net";
import { homedir } from "node:os";
import path from "node:path";

const HERDR_PROTOCOL = 22;
const HERDR_REQUEST_TIMEOUT_MS = 2_000;
const RECAP_COMMAND_TIMEOUT_MS = 5 * 60 * 1_000;
const MAX_COMMAND_OUTPUT = 64 * 1024;

export interface SettledResponse {
	text: string;
	stopReason?: string;
}

export function settledAssistantResponse(entries: readonly unknown[]): SettledResponse | undefined {
	for (let index = entries.length - 1; index >= 0; index -= 1) {
		const entry = entries[index] as {
			type?: unknown;
			message?: { role?: unknown; content?: unknown; stopReason?: unknown };
		} | null;
		if (entry?.type !== "message" || entry.message?.role !== "assistant") continue;

		const content = entry.message.content;
		const text = typeof content === "string"
			? content
			: Array.isArray(content)
				? content
					.filter((part): part is { type: "text"; text: string } =>
						!!part && typeof part === "object" && (part as { type?: unknown }).type === "text" && typeof (part as { text?: unknown }).text === "string",
					)
					.map((part) => part.text)
					.join("\n")
				: "";

		return {
			text,
			stopReason: typeof entry.message.stopReason === "string" ? entry.message.stopReason : undefined,
		};
	}
	return undefined;
}

function recapCliPath(): string {
	const override = process.env.SESSION_RECAP_BIN?.trim();
	return override || path.join(homedir(), ".local", "bin", "session-recap");
}

export function runSessionRecap(args: string[], input = ""): Promise<string> {
	return new Promise((resolve, reject) => {
		const child = spawn(recapCliPath(), args, { stdio: ["pipe", "pipe", "pipe"] });
		let stdout = "";
		let stderr = "";
		let outputTooLarge = false;
		const timeout = setTimeout(() => {
			child.kill("SIGTERM");
			reject(new Error("session-recap timed out"));
		}, RECAP_COMMAND_TIMEOUT_MS);
		timeout.unref?.();

		const finish = (error?: Error) => {
			clearTimeout(timeout);
			if (error) reject(error);
			else resolve(stdout.trim());
		};

		child.once("error", (error) => finish(new Error(`could not start session-recap: ${error.message}`)));
		child.stdout.on("data", (chunk: Buffer) => {
			stdout += chunk.toString("utf8");
			if (Buffer.byteLength(stdout, "utf8") > MAX_COMMAND_OUTPUT) {
				outputTooLarge = true;
				child.kill("SIGTERM");
			}
		});
		child.stderr.on("data", (chunk: Buffer) => {
			stderr += chunk.toString("utf8");
			if (Buffer.byteLength(stderr, "utf8") > MAX_COMMAND_OUTPUT) stderr = stderr.slice(-MAX_COMMAND_OUTPUT);
		});
		child.stdin.on("error", () => {
			// The child close event reports the command outcome, including early exits.
		});
		child.once("close", (code, signal) => {
			if (outputTooLarge) {
				finish(new Error("session-recap returned too much output"));
			} else if (code !== 0) {
				const detail = stderr.trim();
				finish(new Error(detail ? `session-recap failed: ${detail}` : `session-recap exited with ${signal ?? code}`));
			} else {
				finish();
			}
		});
		child.stdin.end(input, "utf8");
	});
}

interface HerdrResponse {
	id?: string;
	result?: unknown;
	error?: { code?: unknown; message?: unknown };
}

export function requestHerdr(
	socketPath: string,
	method: string,
	params: Record<string, unknown> = {},
): Promise<unknown> {
	const id = `herdr-overview:pi:${randomUUID()}`;
	return new Promise((resolve, reject) => {
		const socket = net.createConnection({ path: socketPath });
		let buffer = "";
		let finished = false;
		const finish = (error?: Error, result?: unknown) => {
			if (finished) return;
			finished = true;
			clearTimeout(timeout);
			socket.destroy();
			if (error) reject(error);
			else resolve(result);
		};
		const timeout = setTimeout(
			() => finish(new Error(`Herdr ${method} request timed out`)),
			HERDR_REQUEST_TIMEOUT_MS,
		);
		timeout.unref?.();
		socket.once("error", (error) => finish(error));
		socket.once("close", () => {
			if (!finished) finish(new Error(`Herdr ${method} connection closed before its response`));
		});
		socket.once("connect", () => socket.write(`${JSON.stringify({ id, method, params })}\n`));
		socket.on("data", (chunk) => {
			buffer += chunk.toString("utf8");
			let newline = buffer.indexOf("\n");
			while (newline >= 0) {
				const line = buffer.slice(0, newline);
				buffer = buffer.slice(newline + 1);
				newline = buffer.indexOf("\n");
				if (!line.trim()) continue;
				let message: HerdrResponse;
				try {
					message = JSON.parse(line) as HerdrResponse;
				} catch {
					finish(new Error(`Herdr ${method} returned invalid JSON`));
					return;
				}
				if (message.id !== id) continue;
				if (message.error) {
					const detail = typeof message.error.message === "string" ? message.error.message : "request failed";
					finish(new Error(`Herdr ${method}: ${detail}`));
				} else {
					finish(undefined, message.result);
				}
				return;
			}
		});
	});
}

export async function paneWorkspaceAtPublication(
	socketPath: string | undefined,
	paneId: string | undefined,
): Promise<string | undefined> {
	if (!socketPath || !paneId) return undefined;
	try {
		const result = await requestHerdr(socketPath, "session.snapshot") as {
			snapshot?: { protocol?: unknown; panes?: Array<{ pane_id?: unknown; workspace_id?: unknown }> };
		} | null;
		const snapshot = result?.snapshot;
		if (snapshot?.protocol !== HERDR_PROTOCOL || !Array.isArray(snapshot.panes)) return undefined;
		const pane = snapshot.panes.find((item) => item?.pane_id === paneId);
		return typeof pane?.workspace_id === "string" && pane.workspace_id.trim()
			? pane.workspace_id
			: undefined;
	} catch {
		// Publication is still useful without Herdr membership. Never infer it from UI focus.
		return undefined;
	}
}

export function invokeOverviewReconcile(socketPath: string): Promise<unknown> {
	return requestHerdr(socketPath, "plugin.action.invoke", { action_id: "overview.reconcile" });
}
