import {
	chmodSync,
	closeSync,
	existsSync,
	fsyncSync,
	mkdirSync,
	openSync,
	renameSync,
	readFileSync,
	rmSync,
	writeFileSync,
} from "node:fs";
import { dirname, join } from "node:path";

export const STATE_CUSTOM_TYPE = "standing-reminder-state";
const STATE_DIRECTORY = "standing-reminder";
const STATE_VERSION = 1;

export type ReminderState = {
	reminder: string | null;
	pending: boolean;
};

export function stateFilePath(sessionDir: string, sessionId: string): string {
	return join(sessionDir, STATE_DIRECTORY, `${encodeURIComponent(sessionId)}.json`);
}

export function emptyReminderState(): ReminderState {
	return { reminder: null, pending: false };
}

export function readReminderState(filePath: string):
	| { kind: "missing" }
	| { kind: "ok"; state: ReminderState }
	| { kind: "error"; error: unknown } {
	if (!existsSync(filePath)) return { kind: "missing" };
	try {
		const value: unknown = JSON.parse(readFileSync(filePath, "utf8"));
		if (!value || typeof value !== "object") throw new Error("Invalid state object");
		const record = value as Record<string, unknown>;
		const reminder = record.reminder;
		const pending = record.pending;
		if (
			record.version !== STATE_VERSION ||
			!(reminder === null || typeof reminder === "string") ||
			typeof pending !== "boolean"
		) {
			throw new Error("Unsupported or invalid reminder state");
		}
		return {
			kind: "ok",
			state: { reminder, pending },
		};
	} catch (error) {
		return { kind: "error", error };
	}
}

export function writeReminderState(filePath: string, state: ReminderState): void {
	const directory = dirname(filePath);
	mkdirSync(directory, { recursive: true, mode: 0o700 });
	chmodSync(directory, 0o700);

	const temporaryPath = join(directory, `.standing-reminder-${process.pid}-${Date.now()}-${Math.random().toString(16).slice(2)}.tmp`);
	let fd: number | undefined;
	try {
		fd = openSync(temporaryPath, "wx", 0o600);
		writeFileSync(
			fd,
			JSON.stringify({ version: STATE_VERSION, reminder: state.reminder, pending: state.pending }),
			"utf8",
		);
		fsyncSync(fd);
		closeSync(fd);
		fd = undefined;
		renameSync(temporaryPath, filePath);
		chmodSync(filePath, 0o600);
	} catch (error) {
		if (fd !== undefined) {
			try {
				closeSync(fd);
			} catch {
				// Preserve the original write error.
			}
		}
		try {
			rmSync(temporaryPath, { force: true });
		} catch {
			// Best-effort cleanup.
		}
		throw error;
	}
}

export function hasReminderMarker(entries: unknown[]): boolean {
	return entries.some((entry) => {
		if (!entry || typeof entry !== "object") return false;
		const record = entry as Record<string, unknown>;
		return record.type === "custom" && record.customType === STATE_CUSTOM_TYPE;
	});
}

export function readSessionIdentity(filePath: string):
	| { kind: "ok"; sessionId: string; hasMarker: boolean }
	| { kind: "error"; error: unknown } {
	try {
		const lines = readFileSync(filePath, "utf8").split(/\r?\n/);
		const header = JSON.parse(lines[0] ?? "") as Record<string, unknown>;
		if (header.type !== "session" || typeof header.id !== "string") {
			throw new Error("Invalid session header");
		}
		const hasMarker = lines.slice(1).some((line) => {
			if (!line) return false;
			try {
				const entry = JSON.parse(line) as Record<string, unknown>;
				return entry.type === "custom" && entry.customType === STATE_CUSTOM_TYPE;
			} catch {
				return false;
			}
		});
		return { kind: "ok", sessionId: header.id, hasMarker };
	} catch (error) {
		return { kind: "error", error };
	}
}
