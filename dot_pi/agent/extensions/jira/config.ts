/**
 * Config loader for the jira pi extension.
 */
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

export interface JiraMcpTransportConfig {
	command: string;
	args: string[];
}

export interface JiraConfig {
	enabled: boolean;
	nudgeEveryNTurns: number;
	mcpTransport: JiraMcpTransportConfig | null;
	mcpConfigError: string | null;
}

type BehaviorConfig = {
	enabled?: boolean;
	nudgeEveryNTurns?: number;
};

type PiMcpConfig = {
	mcpServers?: {
		jira?: {
			command?: unknown;
			args?: unknown;
		};
	};
};

export function loadConfig(
	dir: string,
	mcpConfigPath = path.join(os.homedir(), ".pi", "agent", "mcp.json"),
): JiraConfig {
	const behavior = loadBehaviorConfig(dir);
	const transport = loadJiraMcpTransport(mcpConfigPath);

	return {
		enabled: behavior.enabled !== false,
		nudgeEveryNTurns:
			typeof behavior.nudgeEveryNTurns === "number" && behavior.nudgeEveryNTurns >= 0
				? Math.floor(behavior.nudgeEveryNTurns)
				: 5,
		mcpTransport: transport.config,
		mcpConfigError: transport.error,
	};
}

function loadBehaviorConfig(dir: string): BehaviorConfig {
	try {
		return JSON.parse(fs.readFileSync(path.join(dir, "config.json"), "utf8")) as BehaviorConfig;
	} catch {
		return {};
	}
}

function loadJiraMcpTransport(
	mcpConfigPath: string,
): { config: JiraMcpTransportConfig | null; error: string | null } {
	const unavailable =
		"Jira MCP server is unavailable in ~/.pi/agent/mcp.json; run apply_harness_config";

	try {
		const parsed = JSON.parse(fs.readFileSync(mcpConfigPath, "utf8")) as PiMcpConfig;
		const jira = parsed.mcpServers?.jira;
		if (
			typeof jira?.command !== "string" ||
			!jira.command.trim() ||
			!Array.isArray(jira.args) ||
			!jira.args.every((arg) => typeof arg === "string") ||
			jira.args.length === 0
		) {
			return { config: null, error: unavailable };
		}

		return {
			config: {
				command: jira.command.trim(),
				args: [...jira.args],
			},
			error: null,
		};
	} catch {
		return { config: null, error: unavailable };
	}
}
