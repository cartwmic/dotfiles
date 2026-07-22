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
	buildIssueCreationPrompt,
	buildSummaryPrompt,
	clearBind,
	createSessionState,
	detectProviderFromKey,
	effectiveEnabled,
	extractTranscriptAfter,
	lastEntryId,
	formatIssueDraft,
	formatNudgeMessage,
	formatStatus,
	getProviderState,
	loadConfig,
	loadRuntimeState,
	parseCommand,
	parseGeneratedIssue,
	parseIssueDraft,
	sanitizeErrorMessage,
	saveRuntimeState,
	setJiraClientForTests,
	shouldNudge,
	validateIssueBodyAgainstTemplate,
} from "./index.ts";
import { parseGitHubIssueRef } from "./providers/github.ts";

describe("parseCommand", () => {
	test("empty → status", () => {
		expect(parseCommand("")).toEqual({ verb: "status", provider: null, rest: "", rawRest: "" });
		expect(parseCommand(undefined)).toEqual({ verb: "status", provider: null, rest: "", rawRest: "" });
	});
	test("verb only", () => {
		expect(parseCommand("bind")).toEqual({ verb: "bind", provider: null, rest: "", rawRest: "" });
		expect(parseCommand("STATUS")).toEqual({ verb: "status", provider: null, rest: "", rawRest: "" });
	});
	test("verb + provider + rest", () => {
		expect(parseCommand("bind jira PROJ-1")).toEqual({
			verb: "bind",
			provider: "jira",
			rest: "PROJ-1",
			rawRest: "PROJ-1",
		});
		expect(parseCommand("search github auth bug")).toEqual({
			verb: "search",
			provider: "github",
			rest: "auth bug",
			rawRest: "auth bug",
		});
	});
	test("verb + rest (no provider)", () => {
		expect(parseCommand("bind PROJ-1")).toEqual({
			verb: "bind",
			provider: null,
			rest: "PROJ-1",
			rawRest: "PROJ-1",
		});
		expect(parseCommand("search authentication")).toEqual({
			verb: "search",
			provider: null,
			rest: "authentication",
			rawRest: "authentication",
		});
	});
	test("invalid verb", () => {
		expect(parseCommand("nope")).toEqual({ verb: "invalid", provider: null, rest: "nope", rawRest: "nope" });
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

// ---------------------------------------------------------------------------
// Checkpoint-summary feature
// ---------------------------------------------------------------------------

describe("lastEntryId", () => {
	test("returns id of last entry", () => {
		expect(lastEntryId([{ id: "a" }, { id: "b" }])).toBe("b");
	});
	test("null for empty / non-array / missing id", () => {
		expect(lastEntryId([])).toBeNull();
		expect(lastEntryId(undefined as never)).toBeNull();
		expect(lastEntryId([{ nope: 1 }])).toBeNull();
	});
});

describe("extractTranscriptAfter", () => {
	const mk = (id: string, role: string, text: string) => ({
		type: "message",
		id,
		message: { role, content: [{ type: "text", text }] },
	});
	test("collects user+assistant text in order (afterId null)", () => {
		const entries = [mk("1", "user", "do X"), mk("2", "assistant", "did X")];
		expect(extractTranscriptAfter(entries, null)).toBe("USER: do X\n\nASSISTANT: did X");
	});
	test("slices strictly AFTER the cursor id", () => {
		const entries = [mk("1", "assistant", "old"), mk("2", "assistant", "new")];
		expect(extractTranscriptAfter(entries, "1")).toBe("ASSISTANT: new");
		expect(extractTranscriptAfter(entries, "2")).toBe(""); // nothing after last
	});
	test("unknown cursor id -> fail open (include all, never skip)", () => {
		const entries = [mk("1", "assistant", "a"), mk("2", "assistant", "b")];
		expect(extractTranscriptAfter(entries, "gone")).toBe("ASSISTANT: a\n\nASSISTANT: b");
	});
	test("no equal-timestamp double count (position-based)", () => {
		// two entries with the SAME wall-clock but distinct ids
		const entries = [
			{ type: "message", id: "1", timestamp: "2026-07-22T10:00:00Z", message: { role: "assistant", content: [{ type: "text", text: "first" }] } },
			{ type: "message", id: "2", timestamp: "2026-07-22T10:00:00Z", message: { role: "assistant", content: [{ type: "text", text: "second" }] } },
		];
		expect(extractTranscriptAfter(entries, "1")).toBe("ASSISTANT: second");
	});
	test("skips non-message + thinking, keeps text", () => {
		const entries = [
			{ type: "model_change", id: "m" },
			{ type: "message", id: "th", message: { role: "assistant", content: [{ type: "thinking", text: "secret reasoning" }] } },
			mk("k", "assistant", "kept"),
		];
		const out = extractTranscriptAfter(entries, null);
		expect(out).toBe("ASSISTANT: kept");
		expect(out).not.toContain("secret reasoning");
	});
	test("includes tool calls and tool results in order", () => {
		const entries = [
			{ type: "message", id: "1", message: { role: "user", content: "add a test" } },
			{
				type: "message",
				id: "2",
				message: {
					role: "assistant",
					content: [
						{ type: "text", text: "editing file" },
						{ type: "toolCall", name: "edit", arguments: { path: "a.ts" } },
					],
				},
			},
			{
				type: "message",
				id: "3",
				message: {
					role: "toolResult",
					toolName: "edit",
					isError: false,
					content: [{ type: "text", text: "1 file changed" }],
				},
			},
			{
				type: "message",
				id: "4",
				message: {
					role: "toolResult",
					toolName: "bash",
					isError: true,
					content: [{ type: "text", text: "exit 1" }],
				},
			},
		];
		const out = extractTranscriptAfter(entries, null);
		expect(out).toContain("USER: add a test");
		expect(out).toContain("ASSISTANT: editing file");
		expect(out).toContain('ASSISTANT [tool call: edit {"path":"a.ts"}]');
		expect(out).toContain("TOOL RESULT edit: 1 file changed");
		expect(out).toContain("TOOL RESULT bash (error): exit 1");
		// order preserved
		expect(out.indexOf("USER:")).toBeLessThan(out.indexOf("ASSISTANT: editing"));
		expect(out.indexOf("tool call: edit")).toBeLessThan(out.indexOf("TOOL RESULT edit"));
	});
	test("interleaves text and tool calls in encountered order within one message", () => {
		const entries = [
			{
				type: "message",
				id: "1",
				message: {
					role: "assistant",
					content: [
						{ type: "text", text: "first" },
						{ type: "toolCall", name: "a", arguments: {} },
						{ type: "text", text: "second" },
						{ type: "toolCall", name: "b", arguments: {} },
					],
				},
			},
		];
		expect(extractTranscriptAfter(entries, null)).toBe(
			"ASSISTANT: first\n\nASSISTANT [tool call: a]\n\nASSISTANT: second\n\nASSISTANT [tool call: b]",
		);
	});
	test("tool result with no text notes the run", () => {
		const entries = [
			{ type: "message", id: "1", message: { role: "toolResult", toolName: "read", isError: false, content: [{ type: "image", data: "x" }] } },
		];
		expect(extractTranscriptAfter(entries, null)).toBe("TOOL RESULT read: (no text output)");
	});
	test("non-array -> empty", () => {
		expect(extractTranscriptAfter(undefined as never, null)).toBe("");
	});
});

describe("issue creation draft", () => {
	test("prompt includes template, transcript, and optional user input", () => {
		const prompt = buildIssueCreationPrompt({
			provider: "jira",
			template: "## Summary\n## Acceptance Criteria",
			transcript: "USER: add retries",
			userInput: "Focus on timeout handling",
		});
		expect(prompt).toContain("## Acceptance Criteria");
		expect(prompt).toContain("USER: add retries");
		expect(prompt).toContain("Focus on timeout handling");
		expect(prompt).toContain("untrusted content");
		expect(prompt).toContain("valid JSON");
	});

	test("parses strict or fenced model JSON", () => {
		const expected = { title: "Add retries", body: "## Summary\nRetry requests." };
		expect(parseGeneratedIssue(JSON.stringify(expected))).toEqual(expected);
		expect(parseGeneratedIssue(`\`\`\`json\n${JSON.stringify(expected)}\n\`\`\``)).toEqual(expected);
	});

	test("rejects malformed or incomplete model output", () => {
		expect(() => parseGeneratedIssue("not json")).toThrow("valid issue JSON");
		expect(() => parseGeneratedIssue('{"title":"","body":"x"}')).toThrow("title is empty");
		expect(() => parseGeneratedIssue('{"title":"x","body":""}')).toThrow("body is empty");
	});

	test("editable draft round-trips title and body", () => {
		const draft = { title: "Add retries", body: "## Summary\nRetry requests." };
		const editable = formatIssueDraft(draft);
		expect(editable).toStartWith("# Add retries\n\n");
		expect(parseIssueDraft(editable)).toEqual(draft);
		expect(() => parseIssueDraft("Add retries\n\nBody")).toThrow("must start");
		expect(() => parseIssueDraft("# Add retries")).toThrow("body is empty");
	});

	test("requires all managed template headings", () => {
		const template = "## Summary\n<!-- help -->\n\n## Acceptance Criteria";
		expect(() =>
			validateIssueBodyAgainstTemplate(
				"## Summary\nDetails\n\n## Acceptance Criteria\n- [ ] Works",
				template,
			),
		).not.toThrow();
		expect(() => validateIssueBodyAgainstTemplate("## Summary\nDetails", template)).toThrow(
			"## Acceptance Criteria",
		);
	});
});

describe("buildSummaryPrompt", () => {
	test("includes intent + transcript", () => {
		const p = buildSummaryPrompt(
			{ displayKey: "PROJ-1", title: "Add sync", body: "Users want checkpoints" },
			"ASSISTANT: built it",
		);
		expect(p).toContain("[PROJ-1] Add sync");
		expect(p).toContain("Users want checkpoints");
		expect(p).toContain("ASSISTANT: built it");
		expect(p).toContain("do NOT invent");
	});
	test("handles missing body + empty transcript", () => {
		const p = buildSummaryPrompt({ displayKey: "PROJ-2", title: "T" }, "");
		expect(p).toContain("[PROJ-2] T");
		expect(p).toContain("(no session activity captured)");
	});
});

describe("runtime state sidecar", () => {
	const mkDir = () => fs.mkdtempSync(path.join(os.tmpdir(), "issue-state-"));

	test("missing state -> defaults used", () => {
		const dir = mkDir();
		expect(loadRuntimeState(dir)).toEqual({});
		expect(effectiveEnabled(dir, true)).toBe(true);
		expect(effectiveEnabled(dir, false)).toBe(false);
	});
	test("save merges + overrides config default", () => {
		const dir = mkDir();
		saveRuntimeState(dir, { enabled: false });
		expect(effectiveEnabled(dir, true)).toBe(false);
		expect(loadRuntimeState(dir)).toEqual({ enabled: false });
	});
	test("invalid json -> empty", () => {
		const dir = mkDir();
		fs.writeFileSync(path.join(dir, "state.json"), "{ not json");
		expect(loadRuntimeState(dir)).toEqual({});
	});
	test("ignores wrong types", () => {
		const dir = mkDir();
		fs.writeFileSync(path.join(dir, "state.json"), JSON.stringify({ enabled: "yes" }));
		expect(loadRuntimeState(dir)).toEqual({});
	});
});

describe("extractTranscriptAfter — fidelity", () => {
	test("normalizes bare string user content", () => {
		const entries = [
			{ type: "message", id: "1", message: { role: "user", content: "plain string prompt" } },
		];
		expect(extractTranscriptAfter(entries, null)).toBe("USER: plain string prompt");
	});
	test("missing-timestamp entries are NOT dropped (position-based, not time-based)", () => {
		// Every one of these lacks a timestamp; position anchoring keeps them all.
		const entries = [
			{ type: "message", id: "1", message: { role: "assistant", content: [{ type: "text", text: "a" }] } },
			{ type: "message", id: "2", message: { role: "assistant", content: [{ type: "text", text: "b" }] } },
		];
		expect(extractTranscriptAfter(entries, null)).toBe("ASSISTANT: a\n\nASSISTANT: b");
		expect(extractTranscriptAfter(entries, "1")).toBe("ASSISTANT: b");
	});
});

describe("parseCommand — rawRest verbatim fidelity", () => {
	test("preserves internal whitespace of the note", () => {
		const p = parseCommand("sync  double   spaced   note ");
		expect(p.verb).toBe("sync");
		expect(p.provider).toBeNull();
		expect(p.rawRest).toBe("double   spaced   note");
		expect(p.rest).toBe("double spaced note"); // normalized still available
	});
	test("preserves note whitespace with explicit provider", () => {
		const p = parseCommand("sync jira  a  b");
		expect(p.provider).toBe("jira");
		expect(p.rawRest).toBe("a  b");
	});
	test("empty rawRest for bare verb", () => {
		expect(parseCommand("sync").rawRest).toBe("");
	});
});

// --- Handler integration (fake ctx) -------------------------------------
// The extension resolves live providers (Jira MCP / gh) from its own install
// dir, so full end-to-end posting can't run offline. These tests drive the
// registered handler through a fake ctx to lock the PRE-provider guards that do
// not need a live provider: headless fail-closed and the sync note-routing.
import installIssue from "./index.ts";

type IssueCmd = { handler: (args: string, ctx: unknown) => Promise<void> };

function registerAndGetHandler(): (args: string, ctx: unknown) => Promise<void> {
	let cmd: IssueCmd | undefined;
	const pi = {
		registerCommand: (_name: string, def: IssueCmd) => {
			cmd = def;
		},
		on: () => {},
	} as never;
	(installIssue as (p: never) => void)(pi);
	if (!cmd) throw new Error("command not registered");
	return cmd.handler;
}

describe("create handler guards (fake ctx)", () => {
	test("headless creation fails closed before reading the transcript", async () => {
		const handler = registerAndGetHandler();
		let getEntriesCalled = false;
		const ctx = {
			hasUI: false,
			ui: { notify: () => {} },
			sessionManager: {
				getEntries: () => {
					getEntriesCalled = true;
					return [];
				},
			},
		};
		await handler("create github add retries", ctx);
		expect(getEntriesCalled).toBe(false);
	});

	test("creation with no active session model warns and aborts", async () => {
		const handler = registerAndGetHandler();
		const notes: Array<{ msg: string; type: string }> = [];
		const ctx = {
			hasUI: true,
			model: undefined,
			ui: {
				notify: (msg: string, type = "info") => notes.push({ msg, type }),
				editor: async () => undefined,
				confirm: async () => true,
			},
			sessionManager: { getEntries: () => [] },
		};
		await handler("create github add retries", ctx);
		expect(notes.some((n) => n.type === "warning" && /session model/i.test(n.msg))).toBe(true);
	});
});

describe("sync handler guards (fake ctx)", () => {
	test("headless checkpoint fails closed — never reaches transcript/summary", async () => {
		const handler = registerAndGetHandler();
		// warn() is intentionally a no-op without UI, so the observable guarantee is
		// that the checkpoint returns BEFORE reading the transcript or posting.
		let getEntriesCalled = false;
		const ctx = {
			hasUI: false,
			ui: { notify: () => {} },
			sessionManager: {
				getEntries: () => {
					getEntriesCalled = true;
					return [];
				},
			},
		};
		await handler("sync", ctx);
		expect(getEntriesCalled).toBe(false);
	});

	test("UI checkpoint with no active session model warns and aborts", async () => {
		const handler = registerAndGetHandler();
		// hasUI + editor + confirm present, but no session model on ctx.
		const notes: Array<{ msg: string; type: string }> = [];
		const ctx = {
			hasUI: true,
			model: undefined,
			ui: {
				notify: (msg: string, type = "info") => notes.push({ msg, type }),
				editor: async () => undefined,
				confirm: async () => true,
			},
			sessionManager: { getEntries: () => [] },
		};
		await handler("sync", ctx);
		expect(notes.some((n) => n.type === "warning" && /session model/i.test(n.msg))).toBe(true);
	});
});

// --- R2 hardening tests -------------------------------------------------

describe("sanitizeErrorMessage — R2 credential forms", () => {
	const cases: Array<[string, RegExp]> = [
		["Bearer abc.def-123", /c2VjcmV0|abc\.def/],
		["Bearer ab~cd!ef", /ab~cd/],
		["Basic c2VjcmV0OnB3", /c2VjcmV0/],
		['{"Authorization":"Basic c2VjcmV0"}', /c2VjcmV0/],
		["Authorization = Basic c2VjcmV0", /c2VjcmV0/],
		["Authorization: Bearer xyz", /Bearer xyz/],
		// structured Authorization value must not leak ANY component (R3 bypass)
		['Authorization: Digest username="alice", response="sekrit"', /alice|sekrit/],
		["access_token=deadbeef", /deadbeef/],
		['"refresh_token": "r0tten"', /r0tten/],
		// quoted value with internal comma must be redacted whole (R3 bypass)
		['{"access_token":"abc,def"}', /abc,def|,def/],
		// generic secret-bearing keys
		["x-api-key: sk-supersecret", /supersecret/],
		["password=hunter2", /hunter2/],
	];
	for (const [input, secret] of cases) {
		test(`redacts: ${input}`, () => {
			const out = sanitizeErrorMessage(new Error(input));
			expect(out).toContain("[redacted]");
			expect(out).not.toMatch(secret); // raw secret material must not survive
		});
	}
	test("keeps benign text", () => {
		expect(sanitizeErrorMessage(new Error("model not found: x/y"))).toContain("model not found");
	});
});

describe("loadRuntimeState — R2 non-object guards", () => {
	const mk = (content: string) => {
		const dir = fs.mkdtempSync(path.join(os.tmpdir(), "issue-state2-"));
		fs.writeFileSync(path.join(dir, "state.json"), content);
		return dir;
	};
	test("null does not throw (would crash extension startup)", () => {
		const dir = mk("null");
		expect(() => loadRuntimeState(dir)).not.toThrow();
		expect(loadRuntimeState(dir)).toEqual({});
		expect(effectiveEnabled(dir, true)).toBe(true);
	});
	test("array -> empty", () => {
		expect(loadRuntimeState(mk("[1,2]"))).toEqual({});
	});
	test("scalar -> empty", () => {
		expect(loadRuntimeState(mk("42"))).toEqual({});
	});
});

describe("bindKey — R2 anchor reset on rebind", () => {
	test("binding a different key resets lastSyncAt", () => {
		const ps = getProviderState(createSessionState(), "jira");
		bindKey(ps, "PROJ-1");
		ps.lastSyncAt = 1234;
		bindKey(ps, "PROJ-2");
		expect(ps.boundKey).toBe("PROJ-2");
		expect(ps.lastSyncAt).toBeNull();
	});
	test("idempotent rebind of same key preserves lastSyncAt", () => {
		const ps = getProviderState(createSessionState(), "jira");
		bindKey(ps, "PROJ-1");
		ps.lastSyncAt = 5678;
		bindKey(ps, "PROJ-1");
		expect(ps.lastSyncAt).toBe(5678);
	});
	test("bindGeneration bumps on every bind and clear (detects clear->rebind-same-key)", () => {
		const ps = getProviderState(createSessionState(), "jira");
		const g0 = ps.bindGeneration;
		bindKey(ps, "PROJ-1");
		const g1 = ps.bindGeneration;
		expect(g1).toBeGreaterThan(g0);
		// clear then rebind SAME key: boundKey ends equal, but generation advanced
		clearBind(ps);
		bindKey(ps, "PROJ-1");
		expect(ps.bindGeneration).toBeGreaterThan(g1);
		expect(ps.lastSyncEntryId).toBeNull(); // reset survived
	});
});

