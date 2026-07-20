/**
 * Unit tests for jira extension helpers + mock MCP shaping (D9).
 * Run: bun test dot_pi/agent/extensions/jira/
 */
import { describe, expect, test } from "bun:test";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import {
	bindKey,
	clearBind,
	createSessionState,
	formatNudgeMessage,
	formatStatus,
	loadConfig,
	looksLikeIssueKey,
	parseCommand,
	sanitizeErrorMessage,
	setClientForTests,
	shouldNudge,
	toSearchJql,
	toolResultText,
} from "./index.ts";
import { getClient } from "./client.ts";

describe("parseCommand", () => {
	test("empty → status", () => {
		expect(parseCommand("")).toEqual({ verb: "status", rest: "" });
		expect(parseCommand(undefined)).toEqual({ verb: "status", rest: "" });
	});
	test("verbs + rest", () => {
		expect(parseCommand("bind PROJ-1")).toEqual({ verb: "bind", rest: "PROJ-1" });
		expect(parseCommand("search foo bar")).toEqual({ verb: "search", rest: "foo bar" });
		expect(parseCommand("SYNC note")).toEqual({ verb: "sync", rest: "note" });
	});
	test("invalid", () => {
		expect(parseCommand("nope")).toEqual({ verb: "invalid", rest: "nope" });
	});
});

describe("bind/clear state", () => {
	test("bind uppercases and clear resets", () => {
		const s = createSessionState();
		bindKey(s, "proj-42");
		expect(s.boundKey).toBe("PROJ-42");
		s.pendingContextInject = true;
		clearBind(s);
		expect(s.boundKey).toBeNull();
		expect(s.pendingContextInject).toBe(false);
	});
});

describe("shouldNudge", () => {
	test("disabled / zero interval → never", () => {
		expect(shouldNudge(false, 5, 5)).toBe(false);
		expect(shouldNudge(true, 0, 5)).toBe(false);
	});
	test("fires every N", () => {
		expect(shouldNudge(true, 5, 4)).toBe(false);
		expect(shouldNudge(true, 5, 5)).toBe(true);
		expect(shouldNudge(true, 5, 10)).toBe(true);
	});
});

describe("sanitizeErrorMessage", () => {
	test("redacts bearer and tokens", () => {
		const out = sanitizeErrorMessage(
			new Error('Authorization: Bearer abc.def refresh_token=sekrit access_token:"tok"'),
		);
		expect(out).not.toContain("sekrit");
		expect(out).not.toContain("abc.def");
		expect(out).toContain("[redacted]");
	});
});

describe("toSearchJql / looksLikeIssueKey", () => {
	test("plain text wraps", () => {
		expect(toSearchJql(`fix "auth"`)).toContain('summary ~ "fix \\"auth\\""');
	});
	test("jql passthrough", () => {
		expect(toSearchJql('project = FOO AND status = "In Progress"')).toContain("project = FOO");
	});
	test("issue key shape", () => {
		expect(looksLikeIssueKey("ABC-12")).toBe(true);
		expect(looksLikeIssueKey("nope")).toBe(false);
	});
});

describe("formatStatus / nudge", () => {
	test("status fields", () => {
		const s = formatStatus({
			enabled: true,
			boundKey: "X-1",
			lastSyncAt: null,
			nudgeEveryNTurns: 5,
			pendingContextInject: false,
		});
		expect(s).toContain("ON");
		expect(s).toContain("X-1");
		expect(s).toContain("never");
	});
	test("nudge unbound vs bound", () => {
		const s = createSessionState();
		expect(formatNudgeMessage(s)).toContain("unbound");
		bindKey(s, "Y-9");
		expect(formatNudgeMessage(s)).toContain("Y-9");
	});
});

describe("loadConfig", () => {
	test("loads behavior and the generated Jira MCP transport", () => {
		const dir = fs.mkdtempSync(path.join(os.tmpdir(), "jira-cfg-"));
		const mcpConfigPath = path.join(dir, "mcp.json");
		try {
			fs.writeFileSync(
				mcpConfigPath,
				JSON.stringify({
					mcpServers: {
						jira: {
							command: "npx",
							args: ["-y", "mcp-remote", "https://jira.example.test/mcp"],
						},
					},
				}),
			);
			fs.writeFileSync(
				path.join(dir, "config.json"),
				JSON.stringify({ enabled: false, nudgeEveryNTurns: 10 }),
			);

			const c = loadConfig(dir, mcpConfigPath);
			expect(c.enabled).toBe(false);
			expect(c.nudgeEveryNTurns).toBe(10);
			expect(c.mcpTransport).toEqual({
				command: "npx",
				args: ["-y", "mcp-remote", "https://jira.example.test/mcp"],
			});
			expect(c.mcpConfigError).toBeNull();
		} finally {
			fs.rmSync(dir, { recursive: true, force: true });
		}
	});

	test("fails closed when the generated Jira MCP transport is unavailable", () => {
		const dir = fs.mkdtempSync(path.join(os.tmpdir(), "jira-cfg-"));
		try {
			const c = loadConfig(dir, path.join(dir, "missing-mcp.json"));
			expect(c.mcpTransport).toBeNull();
			expect(c.mcpConfigError).toContain("apply_harness_config");
		} finally {
			fs.rmSync(dir, { recursive: true, force: true });
		}
	});
});

describe("mock MCP client call shaping", () => {
	test("getClient refuses an unavailable generated transport", async () => {
		await expect(getClient(loadConfig("/tmp", "/missing-mcp.json"))).rejects.toThrow(
			/apply_harness_config/,
		);
	});

	test("getClient routes to mock; toolResultText parses", async () => {
		const calls: Array<{ name: string; args: Record<string, unknown> }> = [];
		setClientForTests({
			async callTool(name, args = {}) {
				calls.push({ name, args });
				return {
					content: [{ type: "text", text: JSON.stringify({ ok: true, name, args }) }],
				};
			},
			async close() {},
		});
		try {
			const client = await getClient(loadConfig("/tmp", "/missing-mcp.json"));
			const raw = await client.callTool("search_jira_issues", { jql: "a", max_results: 3 });
			const text = toolResultText(raw);
			expect(JSON.parse(text).name).toBe("search_jira_issues");
			expect(calls).toEqual([{ name: "search_jira_issues", args: { jql: "a", max_results: 3 } }]);
		} finally {
			setClientForTests(null);
		}
	});

	test("toolResultText throws sanitized on isError", () => {
		expect(() =>
			toolResultText({
				isError: true,
				content: [{ type: "text", text: "Bearer secret-token-value failed" }],
			}),
		).toThrow(/\[redacted\]/);
	});
});
