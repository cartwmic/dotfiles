import { randomUUID } from "node:crypto";
import { spawn } from "node:child_process";
import net from "node:net";
import { homedir } from "node:os";
import path from "node:path";

const HERDR_REQUEST_TIMEOUT_MS = 2_000;
const RECAP_COMMAND_TIMEOUT_MS = 5 * 60 * 1_000;
const MAX_COMMAND_OUTPUT = 64 * 1024;

function recapCliPath(): string {
	const override = process.env.SESSION_RECAP_BIN?.trim();
	return override || path.join(homedir(), ".local", "bin", "session-recap");
}

export function runSessionRecap(args: string[], input = ""): Promise<string> {
	return new Promise((resolve, reject) => {
		const child = spawn(recapCliPath(), args, { stdio: ["pipe", "pipe", "pipe"] });
		let stdout = "";
		let stderr = "";
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
		});
		child.stderr.on("data", (chunk: Buffer) => {
			stderr += chunk.toString("utf8");
			if (Buffer.byteLength(stderr, "utf8") > MAX_COMMAND_OUTPUT) stderr = stderr.slice(-MAX_COMMAND_OUTPUT);
		});
		child.stdin.on("error", () => {
			// The child close event reports the command outcome, including early exits.
		});
		child.once("close", (code, signal) => {
			if (code !== 0) {
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

export interface CurrentPane {
	paneId: string;
	workspaceId?: string;
}

export async function currentPaneForCaller(
	socketPath: string | undefined,
	callerPaneId: string | undefined,
): Promise<CurrentPane | undefined> {
	if (!socketPath || !callerPaneId) return undefined;
	try {
		const result = await requestHerdr(socketPath, "pane.current", { caller_pane_id: callerPaneId }) as {
			type?: unknown;
			pane?: { pane_id?: unknown; workspace_id?: unknown };
		} | null;
		if (result?.type !== "pane_current") return undefined;
		const paneId = result.pane?.pane_id;
		if (typeof paneId !== "string" || !paneId.trim()) return undefined;
		const workspaceId = result.pane?.workspace_id;
		return {
			paneId,
			...(typeof workspaceId === "string" && workspaceId.trim() ? { workspaceId } : {}),
		};
	} catch {
		// Missing native membership stays unattributed; never infer it from UI focus.
		return undefined;
	}
}

export function invokeOverviewReconcile(socketPath: string): Promise<unknown> {
	return requestHerdr(socketPath, "plugin.action.invoke", { action_id: "overview.reconcile" });
}
