/**
 * Unit tests for the issue extension.
 * Run: bun test dot_pi/agent/extensions/issue/
 */
import { describe, expect, test } from "bun:test";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import {
	bindKey,
	clearBind,
	createSessionState,
	detectProviderFromKey,
	formatNudgeMessage,
	formatStatus,
	getProviderState,
	loadConfig,
	parseCommand,
	sanitizeErrorMessage,
	setJiraClientForTests,
	shouldNudge,
} from "./index.ts";
import { parseGitHubIssueRef } from "./providers/github.ts";

describe("parseCommand", () => {
	test("empty → status", () => {
		expect(parseCommand("")).toEqual({ verb: "status", provider: null, rest: "" });
		expect(parseCommand(undefined)).toEqual({ verb: "status", provider: null, rest: "" });
	});
	test("verb only", () => {
		expect(parseCommand("bind")).toEqual({ verb: "bind", provider: null, rest: "" });
		expect(parseCommand("STATUS")).toEqual({ verb: "status", provider: null, rest: "" });
	});
	test("verb + provider + rest", () => {
		expect(parseCommand("bind jira PROJ-1")).toEqual({
			verb: "bind",
			provider: "jira",
			rest: "PROJ-1",
		});
		expect(parseCommand("search github auth bug")).toEqual({
			verb: "search",
			provider: "github",
			rest: "auth bug",
		});
	});
	test("verb + rest (no provider)", () => {
		expect(parseCommand("bind PROJ-1")).toEqual({
			verb: "bind",
			provider: null,
			rest: "PROJ-1",
		});
		expect(parseCommand("search authentication")).toEqual({
			verb: "search",
			provider: null,
			rest: "authentication",
		});
	});
	test("invalid verb", () => {
		expect(parseCommand("nope")).toEqual({ verb: "invalid", provider: null, rest: "nope" });
	});
});

describe("detectProviderFromKey", () => {
	test("jira keys", () => {
		expect(detectProviderFromKey("PROJ-123")).toBe("jira");
		expect(detectProviderFromKey("FOO2-99")).toBe("jira");
		expect(detectProviderFromKey("abc-1")).toBe("jira");
	});
	test("github keys", () => {
		expect(detectProviderFromKey("123")).toBe("github");
		expect(detectProviderFromKey("owner/repo#42")).toBe("github");
	});
	test("unknown", () => {
		expect(detectProviderFromKey("random")).toBeNull();
		expect(detectProviderFromKey("")).toBeNull();
	});
});

describe("parseGitHubIssueRef", () => {
	test("number only", () => {
		expect(parseGitHubIssueRef("123")).toEqual({ number: 123 });
	});
	test("full ref", () => {
		expect(parseGitHubIssueRef("owner/repo#42")).toEqual({ repo: "owner/repo", number: 42 });
	});
	test("invalid", () => {
		expect(parseGitHubIssueRef("random")).toBeNull();
		expect(parseGitHubIssueRef("")).toBeNull();
	});
});

describe("session state", () => {
	test("multi-provider binds", () => {
		const state = createSessionState();
		const jiraPs = getProviderState(state, "jira");
		const githubPs = getProviderState(state, "github");

		bindKey(jiraPs, "PROJ-42");
		expect(jiraPs.boundKey).toBe("PROJ-42");
		expect(githubPs.boundKey).toBeNull();

		bindKey(githubPs, "123");
		expect(githubPs.boundKey).toBe("123");

		clearBind(jiraPs);
		expect(jiraPs.boundKey).toBeNull();
		expect(githubPs.boundKey).toBe("123");
	});

	test("nudge cadence", () => {
		expect(shouldNudge(false, 5, 5)).toBe(false);
		expect(shouldNudge(true, 0, 5)).toBe(false);
		expect(shouldNudge(true, 5, 4)).toBe(false);
		expect(shouldNudge(true, 5, 5)).toBe(true);
		expect(shouldNudge(true, 5, 10)).toBe(true);
	});

	test("bindKey clears pendingPayload", () => {
		const ps = getProviderState(createSessionState(), "jira");
		ps.pendingPayload = "old payload";
		bindKey(ps, "PROJ-1");
		expect(ps.boundKey).toBe("PROJ-1");
		expect(ps.pendingPayload).toBeUndefined();
		expect(ps.pendingContextInject).toBe(false);
	});

	test("clearBind clears pendingPayload", () => {
		const ps = getProviderState(createSessionState(), "jira");
		ps.pendingPayload = "old payload";
		ps.lastSyncAt = Date.now();
		clearBind(ps);
		expect(ps.boundKey).toBeNull();
		expect(ps.lastSyncAt).toBeNull();
		expect(ps.pendingPayload).toBeUndefined();
		expect(ps.pendingContextInject).toBe(false);
	});
});

describe("formatStatus", () => {
	test("shows all providers", () => {
		const s = formatStatus({
			enabled: true,
			providerStates: [
				{ name: "jira", boundKey: "X-1", lastSyncAt: null },
				{ name: "github", boundKey: null, lastSyncAt: Date.now() - 300_000 },
			],
			nudgeEveryNTurns: 5,
		});
		expect(s).toContain("ON");
		expect(s).toContain("jira: X-1");
		expect(s).toContain("github: unbound");
		expect(s).toContain("5m ago");
	});
});

describe("formatNudgeMessage", () => {
	test("multi-provider nudge", () => {
		const state = createSessionState();
		bindKey(getProviderState(state, "jira"), "PROJ-1");
		bindKey(getProviderState(state, "github"), "123");
		const msg = formatNudgeMessage(state, ["jira", "github"]);
		expect(msg).toContain("jira PROJ-1");
		expect(msg).toContain("github 123");
		expect(msg).toContain("/issue sync");
	});
});

describe("sanitizeErrorMessage", () => {
	test("redacts secrets", () => {
		const out = sanitizeErrorMessage(
			new Error('Authorization: Bearer abc.def refresh_token=sekrit access_token:"tok"'),
		);
		expect(out).not.toContain("sekrit");
		expect(out).not.toContain("abc.def");
		expect(out).toContain("[redacted]");
	});
});

describe("loadConfig", () => {
	test("loads behavior and jira MCP transport", () => {
		const dir = fs.mkdtempSync(path.join(os.tmpdir(), "issue-cfg-"));
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
			expect(c.behavior.enabled).toBe(false);
			expect(c.behavior.nudgeEveryNTurns).toBe(10);
			expect(c.jira.mcpTransport).toEqual({
				command: "npx",
				args: ["-y", "mcp-remote", "https://jira.example.test/mcp"],
			});
			expect(c.jira.mcpConfigError).toBeNull();
		} finally {
			fs.rmSync(dir, { recursive: true, force: true });
		}
	});

	test("fails closed when jira MCP transport missing", () => {
		const dir = fs.mkdtempSync(path.join(os.tmpdir(), "issue-cfg-"));
		try {
			const c = loadConfig(dir, path.join(dir, "missing-mcp.json"));
			expect(c.jira.mcpTransport).toBeNull();
			expect(c.jira.mcpConfigError).toContain("apply_harness_config");
		} finally {
			fs.rmSync(dir, { recursive: true, force: true });
		}
	});
});

describe("mock Jira provider", () => {
	test("setJiraClientForTests routes calls", async () => {
		const { JiraProvider } = await import("./providers/jira.ts");
		const calls: Array<{ name: string; args: Record<string, unknown> }> = [];
		setJiraClientForTests({
			async callTool(name, args = {}) {
				calls.push({ name, args });
				return {
					content: [{ type: "text", text: JSON.stringify({ ok: true, name, args }) }],
				};
			},
			async close() {},
		});
		try {
			const p = new JiraProvider({
				mcpTransport: { command: "npx", args: ["test"] },
				mcpConfigError: null,
			});
			const result = await p.searchIssues("test");
			expect(calls.length).toBeGreaterThan(0);
			expect(result.issues).toBeDefined();
		} finally {
			setJiraClientForTests(null);
		}
	});

	test("addComment throws on isError", async () => {
		const { JiraProvider } = await import("./providers/jira.ts");
		setJiraClientForTests({
			async callTool() {
				return {
					isError: true,
					content: [{ type: "text", text: "Comment failed" }],
				};
			},
			async close() {},
		});
		try {
			const p = new JiraProvider({
				mcpTransport: { command: "npx", args: ["test"] },
				mcpConfigError: null,
			});
			await expect(p.addComment("PROJ-1", "test")).rejects.toThrow();
		} finally {
			setJiraClientForTests(null);
		}
	});

	test("transitionIssue throws on isError", async () => {
		const { JiraProvider } = await import("./providers/jira.ts");
		setJiraClientForTests({
			async callTool() {
				return {
					isError: true,
					content: [{ type: "text", text: "Transition failed" }],
				};
			},
			async close() {},
		});
		try {
			const p = new JiraProvider({
				mcpTransport: { command: "npx", args: ["test"] },
				mcpConfigError: null,
			});
			await expect(p.transitionIssue("PROJ-1", "21")).rejects.toThrow();
		} finally {
			setJiraClientForTests(null);
		}
	});

	test("createIssue requires project key", async () => {
		const { JiraProvider } = await import("./providers/jira.ts");
		setJiraClientForTests({
			async callTool() {
				return {
					content: [{ type: "text", text: JSON.stringify({ key: "PROJ-1" }) }],
				};
			},
			async close() {},
		});
		try {
			const p = new JiraProvider({
				mcpTransport: { command: "npx", args: ["test"] },
				mcpConfigError: null,
			});
			await expect(p.createIssue({ title: "Test" })).rejects.toThrow("project key is required");
		} finally {
			setJiraClientForTests(null);
		}
	});

	test("createIssue succeeds with project key", async () => {
		const { JiraProvider } = await import("./providers/jira.ts");
		setJiraClientForTests({
			async callTool() {
				return {
					content: [{ type: "text", text: JSON.stringify({ key: "PROJ-1" }) }],
				};
			},
			async close() {},
		});
		try {
			const p = new JiraProvider({
				mcpTransport: { command: "npx", args: ["test"] },
				mcpConfigError: null,
			});
			const issue = await p.createIssue({ title: "Test", project: "PROJ" });
			expect(issue.key).toBe("PROJ-1");
		} finally {
			setJiraClientForTests(null);
		}
	});

	test("searchIssues passes single-clause JQL through without wrapping", async () => {
		const { JiraProvider } = await import("./providers/jira.ts");
		const calls: Array<{ name: string; args: Record<string, unknown> }> = [];
		setJiraClientForTests({
			async callTool(name, args = {}) {
				calls.push({ name, args });
				return {
					content: [{ type: "text", text: JSON.stringify({ issues: [], total: 0 }) }],
				};
			},
			async close() {},
		});
		try {
			const p = new JiraProvider({
				mcpTransport: { command: "npx", args: ["test"] },
				mcpConfigError: null,
			});
			await p.searchIssues("project = ABC");
			expect(calls[0].args.jql).toBe("project = ABC");
			await p.searchIssues("summary ~ \"login\"");
			expect(calls[1].args.jql).toBe("summary ~ \"login\"");
			await p.searchIssues("status != Done");
			expect(calls[2].args.jql).toBe("status != Done");
		} finally {
			setJiraClientForTests(null);
		}
	});

	test("getIssue converts REST self URL to browse URL", async () => {
		const { JiraProvider } = await import("./providers/jira.ts");
		setJiraClientForTests({
			async callTool() {
				return {
					content: [{ type: "text", text: JSON.stringify({
						key: "PROJ-1",
						self: "https://jira.example.com/rest/api/2/issue/12345",
						fields: { summary: "Test", status: { name: "Open" } }
					}) }],
				};
			},
			async close() {},
		});
		try {
			const p = new JiraProvider({
				mcpTransport: { command: "npx", args: ["test"] },
				mcpConfigError: null,
			});
			const issue = await p.getIssue("PROJ-1");
			expect(issue.url).toBe("https://jira.example.com/browse/PROJ-1");
		} finally {
			setJiraClientForTests(null);
		}
	});

	test("getIssue extracts text from ADF description", async () => {
		const { JiraProvider } = await import("./providers/jira.ts");
		setJiraClientForTests({
			async callTool() {
				return {
					content: [{ type: "text", text: JSON.stringify({
						key: "PROJ-1",
						self: "",
						fields: {
							summary: "Test",
							status: { name: "Open" },
							description: {
								type: "doc",
								content: [
									{ type: "paragraph", content: [{ type: "text", text: "Hello " }] },
									{ type: "paragraph", content: [{ type: "text", text: "world" }] }
								]
							}
						}
					}) }],
				};
			},
			async close() {},
		});
		try {
			const p = new JiraProvider({
				mcpTransport: { command: "npx", args: ["test"] },
				mcpConfigError: null,
			});
			const issue = await p.getIssue("PROJ-1");
			expect(issue.body).toBe("Hello world");
		} finally {
			setJiraClientForTests(null);
		}
	});
});
