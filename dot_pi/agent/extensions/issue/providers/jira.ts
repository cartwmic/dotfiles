/**
 * Jira provider — backed by an MCP-remote stdio client.
 * Reads transport config from ~/.pi/agent/mcp.json under mcpServers.jira.
 */
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { sanitizeErrorMessage } from "../helpers.ts";
import type { CreateIssueInput, Issue, IssueProvider, SearchResult, Transition } from "./types.ts";

export interface JiraMcpTransportConfig {
	command: string;
	args: string[];
}

export interface JiraConfig {
	mcpTransport: JiraMcpTransportConfig | null;
	mcpConfigError: string | null;
}

interface McpClientLike {
	callTool(name: string, args?: Record<string, unknown>): Promise<unknown>;
	close(): Promise<void>;
}

type RealHandles = {
	client: {
		callTool: (req: { name: string; arguments?: Record<string, unknown> }) => Promise<unknown>;
		close: () => Promise<void>;
	};
	transport: { close: () => Promise<void> };
};

let testOverride: McpClientLike | null = null;
let live: RealHandles | null = null;

export function setJiraClientForTests(client: McpClientLike | null): void {
	testOverride = client;
}

export async function closeJiraClient(): Promise<void> {
	if (testOverride) {
		await testOverride.close();
		testOverride = null;
		return;
	}
	if (!live) return;
	const h = live;
	live = null;
	try {
		await h.client.close();
	} catch {
		/* ignore */
	}
	try {
		await h.transport.close();
	} catch {
		/* ignore */
	}
}

function toolResultText(result: unknown): string {
	if (!result || typeof result !== "object") return String(result ?? "");
	const r = result as { content?: Array<{ type?: string; text?: string }>; isError?: boolean };
	if (r.isError) {
		const t = (r.content ?? []).map((c) => c.text ?? "").join("\n");
		throw new Error(sanitizeErrorMessage(t || "Jira tool error"));
	}
	return (r.content ?? [])
		.filter((c) => c && c.type === "text" && typeof c.text === "string")
		.map((c) => c.text as string)
		.join("\n");
}

async function getMcpClient(cfg: JiraConfig): Promise<McpClientLike> {
	if (testOverride) return testOverride;
	if (!live) live = await connectLive(cfg);
	return {
		async callTool(name, args = {}) {
			try {
				return await live!.client.callTool({ name, arguments: args });
			} catch (err) {
				throw new Error(sanitizeErrorMessage(err));
			}
		},
		async close() {
			await closeJiraClient();
		},
	};
}

async function connectLive(cfg: JiraConfig): Promise<RealHandles> {
	if (!cfg.mcpTransport) {
		throw new Error(cfg.mcpConfigError ?? "Jira MCP server is unavailable");
	}

	const sdkRoot = resolveSdkRoot();
	const { Client } = await import(`${sdkRoot}/dist/esm/client/index.js`);
	const { StdioClientTransport } = await import(`${sdkRoot}/dist/esm/client/stdio.js`);

	const transport = new StdioClientTransport({
		command: cfg.mcpTransport.command,
		args: [...cfg.mcpTransport.args],
		env: process.env as Record<string, string>,
		stderr: "ignore",
	});
	const client = new Client({ name: "pi-issue-extension-jira", version: "0.1.0" });
	try {
		await client.connect(transport);
	} catch (err) {
		try {
			await transport.close();
		} catch {
			/* ignore */
		}
		throw new Error(`Jira MCP connect failed: ${sanitizeErrorMessage(err)}`);
	}
	return { client, transport };
}

function resolveSdkRoot(): string {
	const home = homedir();
	const candidates = [
		join(home, ".local/share/mise/installs/node/24.12.0/lib/node_modules/pi-mcp-adapter/node_modules/@modelcontextprotocol/sdk"),
		join(home, ".local/share/mise/installs/node/current/lib/node_modules/pi-mcp-adapter/node_modules/@modelcontextprotocol/sdk"),
	];
	for (const c of candidates) {
		if (existsSync(join(c, "package.json"))) return c;
	}
	throw new Error(
		"@modelcontextprotocol/sdk not found beside pi-mcp-adapter (see ~/.mcp-auth for OAuth cache)",
	);
}

function extractAdfText(node: Record<string, unknown>): string {
	if (typeof node.text === "string") return node.text;
	const content = node.content;
	if (Array.isArray(content)) {
		return content.map((c) => extractAdfText(c as Record<string, unknown>)).join("");
	}
	return "";
}

function extractDescription(fields: Record<string, unknown>): string | undefined {
	const desc = fields.description;
	if (typeof desc === "string") return desc;
	if (desc && typeof desc === "object") {
		return extractAdfText(desc as Record<string, unknown>) || undefined;
	}
	return undefined;
}

function toBrowseUrl(selfUrl: string, key: string): string {
	if (!selfUrl) return "";
	// Convert REST API URL to browse URL
	// e.g. https://jira.example.com/rest/api/2/issue/12345 → https://jira.example.com/browse/PROJ-123
	return selfUrl.replace(/\/rest\/api\/\d+\/issue\/\d+$/, `/browse/${key}`);
}

function parseIssueJson(text: string, key: string): Issue {
	const data = JSON.parse(text) as Record<string, unknown>;
	const fields = (data.fields ?? {}) as Record<string, unknown>;
	const statusObj = (fields.status ?? {}) as Record<string, unknown>;
	const statusName = typeof statusObj.name === "string" ? statusObj.name : "Unknown";
	const summary = typeof fields.summary === "string" ? fields.summary : "";
	const description = extractDescription(fields);
	const selfUrl = typeof data.self === "string" ? data.self : "";
	const url = toBrowseUrl(selfUrl, key);
	return {
		key,
		displayKey: key,
		title: summary,
		body: description,
		status: statusName,
		url,
		provider: "jira",
	};
}

export class JiraProvider implements IssueProvider {
	readonly name = "jira";
	readonly isAvailable: boolean;

	constructor(private cfg: JiraConfig) {
		this.isAvailable = cfg.mcpTransport !== null;
	}

	async getIssue(key: string): Promise<Issue> {
		const client = await getMcpClient(this.cfg);
		const raw = await client.callTool("get_jira_issue", { issue_key: key });
		const text = toolResultText(raw);
		return parseIssueJson(text, key);
	}

	async searchIssues(query: string): Promise<SearchResult> {
		const client = await getMcpClient(this.cfg);
		const jql = toSearchJql(query);
		const raw = await client.callTool("search_jira_issues", { jql, max_results: 10 });
		const text = toolResultText(raw);
		const data = JSON.parse(text) as { issues?: Array<Record<string, unknown>>; total?: number };
		const issues = (data.issues ?? []).map((item) => {
			const k = String(item.key ?? "UNKNOWN");
			return parseIssueJson(JSON.stringify(item), k);
		});
		return { issues, total: typeof data.total === "number" ? data.total : issues.length };
	}

	async createIssue(input: CreateIssueInput): Promise<Issue> {
		const client = await getMcpClient(this.cfg);
		const project = input.project;
		if (!project) {
			throw new Error(
				"Jira project key is required. Bind an issue first, or specify project in create command.",
			);
		}
		const raw = await client.callTool("create_jira_issue", {
			project_key: project,
			summary: input.title,
			description: input.body ?? "",
			issue_type: "Task",
		});
		const text = toolResultText(raw);
		const data = JSON.parse(text) as Record<string, unknown>;
		const key = String(data.key ?? "");
		return parseIssueJson(text, key);
	}

	async addComment(key: string, body: string): Promise<void> {
		const client = await getMcpClient(this.cfg);
		const raw = await client.callTool("add_jira_comment", { issue_key: key, comment: body });
		toolResultText(raw); // throws on isError
	}

	async listTransitions(key: string): Promise<Transition[]> {
		const client = await getMcpClient(this.cfg);
		const raw = await client.callTool("get_jira_transitions", { issue_key: key });
		const text = toolResultText(raw);
		const data = JSON.parse(text) as { transitions?: Array<{ id?: string; name?: string }> };
		return (data.transitions ?? [])
			.filter((t) => typeof t.id === "string" && typeof t.name === "string")
			.map((t) => ({ id: t.id!, name: t.name! }));
	}

	async transitionIssue(key: string, transitionId: string): Promise<void> {
		const client = await getMcpClient(this.cfg);
		const raw = await client.callTool("transition_jira_issue", {
			issue_key: key,
			transition_id: transitionId,
		});
		toolResultText(raw); // throws on isError
	}
}

/** Heuristic: treat as JQL if it contains JQL operators/keywords. */
function toSearchJql(textOrJql: string): string {
	const t = textOrJql.trim();
	if (!t) return "assignee = currentUser() ORDER BY updated DESC";
	// Multi-clause JQL
	if (/\b(AND|OR|ORDER BY)\b/i.test(t)) return t;
	// Single-clause JQL: known field followed by an operator
	if (/^(project|key|summary|description|status|assignee|reporter|priority|labels|components|fixVersion|affectedVersion|issuetype|created|updated|duedate)\s*[=~!><]/i.test(t)) return t;
	const escaped = t.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
	return `summary ~ "${escaped}" OR description ~ "${escaped}" ORDER BY updated DESC`;
}
