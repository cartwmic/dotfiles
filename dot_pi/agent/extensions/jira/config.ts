/**
 * Config loader for the jira pi extension.
 */
import * as fs from "node:fs";
import * as path from "node:path";

export const DEFAULT_JIRA_MCP_URL =
	"https://app-mcp-jira-prod-j6a1bj7j.azurewebsites.net/mcp";

export interface JiraConfig {
	enabled: boolean;
	nudgeEveryNTurns: number;
	jiraMcpUrl: string;
	mcpRemoteCommand: string;
	mcpRemoteArgs: string[];
}

export function loadConfig(dir: string): JiraConfig {
	try {
		const raw = fs.readFileSync(path.join(dir, "config.json"), "utf8");
		const parsed = JSON.parse(raw) as Partial<JiraConfig>;
		const nudge =
			typeof parsed.nudgeEveryNTurns === "number" && parsed.nudgeEveryNTurns >= 0
				? Math.floor(parsed.nudgeEveryNTurns)
				: 5;
		return {
			enabled: parsed.enabled !== false,
			nudgeEveryNTurns: nudge,
			jiraMcpUrl:
				typeof parsed.jiraMcpUrl === "string" && parsed.jiraMcpUrl.trim()
					? parsed.jiraMcpUrl.trim()
					: DEFAULT_JIRA_MCP_URL,
			mcpRemoteCommand:
				typeof parsed.mcpRemoteCommand === "string" && parsed.mcpRemoteCommand.trim()
					? parsed.mcpRemoteCommand.trim()
					: "npx",
			mcpRemoteArgs: Array.isArray(parsed.mcpRemoteArgs)
				? parsed.mcpRemoteArgs.map(String)
				: ["-y", "mcp-remote"],
		};
	} catch {
		return {
			enabled: true,
			nudgeEveryNTurns: 5,
			jiraMcpUrl: DEFAULT_JIRA_MCP_URL,
			mcpRemoteCommand: "npx",
			mcpRemoteArgs: ["-y", "mcp-remote"],
		};
	}
}
