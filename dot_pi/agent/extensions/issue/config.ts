/**
 * Config loader for the issue-tracking pi extension.
 */
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { JiraConfig, JiraMcpTransportConfig } from "./providers/jira.ts";

export interface IssueBehaviorConfig {
	enabled: boolean;
	nudgeEveryNTurns: number;
}

export interface IssueExtensionConfig {
	behavior: IssueBehaviorConfig;
	jira: JiraConfig;
}

type RawBehaviorConfig = {
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
): IssueExtensionConfig {
	return {
		behavior: loadBehaviorConfig(dir),
		jira: loadJiraConfig(mcpConfigPath),
	};
}

function loadBehaviorConfig(dir: string): IssueBehaviorConfig {
	let raw: RawBehaviorConfig = {};
	try {
		raw = JSON.parse(fs.readFileSync(path.join(dir, "config.json"), "utf8")) as RawBehaviorConfig;
	} catch {
		/* use defaults */
	}
	return {
		enabled: raw.enabled !== false,
		nudgeEveryNTurns:
			typeof raw.nudgeEveryNTurns === "number" && raw.nudgeEveryNTurns >= 0
				? Math.floor(raw.nudgeEveryNTurns)
				: 5,
	};
}

function loadJiraConfig(mcpConfigPath: string): JiraConfig {
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
			return { mcpTransport: null, mcpConfigError: unavailable };
		}

		return {
			mcpTransport: {
				command: jira.command.trim(),
				args: [...jira.args],
			},
			mcpConfigError: null,
		};
	} catch {
		return { mcpTransport: null, mcpConfigError: unavailable };
	}
}
