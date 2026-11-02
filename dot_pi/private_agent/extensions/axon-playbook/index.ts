import { execFile } from "node:child_process";
import { homedir } from "node:os";
import { join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export const CUSTOM_TYPE = "axon_playbook";
export const TIMEOUT_MS = 3_000;
const MAX_BYTES = 256 * 1024;

export const defaultScript = (home = homedir()): string =>
	join(home, ".local/share/agent-harness/external-skills/axon-agents-playbook/bin/playbook-context");

/** The script's trimmed stdout, or "" when it is missing, not executable, fails, times out, or prints nothing. */
export function runPlaybookContext(script: string, cwd: string, timeoutMs = TIMEOUT_MS): Promise<string> {
	return new Promise((resolve) => {
		try {
			execFile(script, [cwd], { timeout: timeoutMs, killSignal: "SIGKILL", maxBuffer: MAX_BYTES, encoding: "utf8" }, (err, stdout) =>
				resolve(err ? "" : stdout.trim()),
			);
		} catch {
			resolve("");
		}
	});
}

export const formatBlock = (text: string): string => `<axon_playbook>\n${text}\n</axon_playbook>`;

/** True when a playbook message is still in the model's context: after the last compaction, or kept by it. */
export function playbookInContext(branch: ReadonlyArray<any>): boolean {
	const compaction = branch.findLastIndex((e) => e.type === "compaction");
	let from = 0;
	if (compaction >= 0) {
		const kept = branch.findIndex((e) => e.id === branch[compaction].firstKeptEntryId);
		from = kept >= 0 && kept < compaction ? kept : compaction;
	}
	return branch.slice(from).some((e) => e.type === "custom_message" && e.customType === CUSTOM_TYPE);
}

export interface Options {
	script?: string;
	timeoutMs?: number;
	env?: Record<string, string | undefined>;
}

/**
 * Pi's counterpart of the Claude Code SessionStart hook that runs the Axon playbook's `bin/playbook-context`.
 *
 * `session_start` cannot add context, so the first `before_agent_start` of a session runs the script for `ctx.cwd` and
 * returns its output as a hidden custom message, the way the hindsight extension injects recalled memories. That message
 * is stored in the session, so it is not repeated on later turns, and a resumed or forked session that already holds it
 * is not injected twice. Compaction summarizes the message away, so it is injected once more on the next turn after one.
 * Any failure injects nothing and says nothing.
 */
export function create(options: Options = {}) {
	return function (pi: ExtensionAPI): void {
		const env = options.env ?? process.env;
		// A subagent child is not a session start (Claude Code's SessionStart hook does not fire for subagents either).
		if (env.PI_SUBAGENT_CHILD === "1") return;
		const script = options.script ?? defaultScript();
		let attempted = false; // serializable state only; every handler uses its own per-call ctx

		pi.on("session_compact", () => {
			attempted = false;
		});

		pi.on("before_agent_start", async (_event, ctx) => {
			if (attempted) return;
			attempted = true;
			try {
				if (playbookInContext(ctx.sessionManager.getBranch() as ReadonlyArray<any>)) return;
				const text = await runPlaybookContext(script, ctx.cwd, options.timeoutMs);
				if (!text) return;
				return { message: { customType: CUSTOM_TYPE, content: formatBlock(text), display: false } };
			} catch {
				return;
			}
		});
	};
}

export default create();
