/**
 * Own mcp-remote stdio MCP client for Jira (D1 + D8).
 * Tests inject a mock via setClientForTests.
 */
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import type { JiraConfig } from "./config.ts";
import { sanitizeErrorMessage } from "./helpers.ts";

export interface JiraMcpClient {
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

let testOverride: JiraMcpClient | null = null;
let live: RealHandles | null = null;

export function setClientForTests(client: JiraMcpClient | null): void {
	testOverride = client;
}

export async function getClient(cfg: JiraConfig): Promise<JiraMcpClient> {
	if (testOverride) return testOverride;
	if (!live) live = await connectLive(cfg);
	return wrapLive(live);
}

function wrapLive(handles: RealHandles): JiraMcpClient {
	return {
		async callTool(name, args = {}) {
			try {
				return await handles.client.callTool({ name, arguments: args });
			} catch (err) {
				throw new Error(sanitizeErrorMessage(err));
			}
		},
		async close() {
			await closeLive();
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
	const client = new Client({ name: "pi-jira-extension", version: "0.1.0" });
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

async function closeLive(): Promise<void> {
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

export async function closeClient(): Promise<void> {
	if (testOverride) {
		await testOverride.close();
		return;
	}
	await closeLive();
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

/** Extract text payload from MCP tool result content blocks. */
export function toolResultText(result: unknown): string {
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
