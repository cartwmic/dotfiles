import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

/** The shared classifier (agent-harness README, "Pattern-kill guard"); Claude's hook runs the same script. */
export const GUARD_SCRIPT = join(homedir(), ".local/share/agent-harness/hooks/refuse_pattern_kill.py");

const REFUSAL_MARK = "refused in agent sessions";

/**
 * The reason to give the agent when `command` runs pkill or killall, else undefined. Fails open: a missing script, a missing python3,
 * a timeout or any other exit code allows the command (python3 itself exits 2 on a missing file, so the stderr text is checked too).
 */
export function refusal(command: string, script: string = GUARD_SCRIPT): string | undefined {
	if (!existsSync(script)) return undefined;
	const run = spawnSync("python3", [script], { input: JSON.stringify({ tool_input: { command } }), encoding: "utf8", timeout: 10_000 });
	return run.status === 2 && run.stderr.includes(REFUSAL_MARK) ? run.stderr.trim() : undefined;
}

/** The tool_call handler: a bash call that runs pkill or killall is blocked. Other tools and other bash calls pass through. */
export const guard =
	(script: string = GUARD_SCRIPT) =>
	(event: { toolName: string; input: unknown }) => {
		if (event.toolName !== "bash") return;
		const command = (event.input as { command?: unknown }).command;
		if (typeof command !== "string") return;
		const reason = refusal(command, script);
		if (reason) return { block: true as const, reason };
	};

/**
 * An agent's bash call that runs pkill or killall is blocked with a reason that names the exact-PID alternative. The user's own `!` bash
 * in Pi is a different event (user_bash) and is not touched.
 */
export default function (pi: ExtensionAPI) {
	pi.on("tool_call", guard());
}
