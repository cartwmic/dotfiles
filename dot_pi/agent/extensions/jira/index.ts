/**
 * jira — standalone work-profile pi extension for session Jira binding,
 * slash-command ticket ops via own mcp-remote client, UI nudges, and
 * on-demand context inject (no auto-inject).
 *
 * See README.md + openspec change add-jira-pi-extension.
 */
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI, ExtensionCommandContext } from "@mariozechner/pi-coding-agent";
import { closeClient, getClient, toolResultText } from "./client.ts";
import { loadConfig } from "./config.ts";
import {
	bindKey,
	clearBind,
	createSessionState,
	formatNudgeMessage,
	formatStatus,
	looksLikeIssueKey,
	parseCommand,
	sanitizeErrorMessage,
	shouldNudge,
	toSearchJql,
} from "./helpers.ts";

function extensionDir(): string {
	return path.dirname(fileURLToPath(import.meta.url));
}

function warn(ctx: ExtensionCommandContext, msg: string): void {
	if (ctx.hasUI) ctx.ui.notify(msg, "warning");
}

function info(ctx: ExtensionCommandContext, msg: string): void {
	if (ctx.hasUI) ctx.ui.notify(msg, "info");
}

async function confirm(ctx: ExtensionCommandContext, message: string): Promise<boolean> {
	if (!ctx.hasUI || typeof ctx.ui.confirm !== "function") return true;
	try {
		return Boolean(await ctx.ui.confirm("Jira", message));
	} catch {
		return false;
	}
}

export default function (pi: ExtensionAPI): void {
	const dir = extensionDir();
	const cfg = loadConfig(dir);
	let enabled = cfg.enabled;
	const state = createSessionState();

	async function withClient<T>(
		ctx: ExtensionCommandContext,
		fn: (client: Awaited<ReturnType<typeof getClient>>) => Promise<T>,
	): Promise<T | undefined> {
		try {
			const client = await getClient(cfg);
			return await fn(client);
		} catch (err) {
			warn(ctx, `Jira: ${sanitizeErrorMessage(err)}`);
			return undefined;
		}
	}

	pi.registerCommand("jira", {
		description:
			"Jira session helper (on|off|toggle|status|bind|clear|show|search|create|sync|transition|context)",
		getArgumentCompletions: (prefix: string) =>
			[
				"on",
				"off",
				"toggle",
				"status",
				"bind",
				"clear",
				"show",
				"search",
				"create",
				"sync",
				"transition",
				"context",
			]
				.filter((v) => v.startsWith(prefix.toLowerCase()))
				.map((v) => ({ value: v, label: v })),
		handler: async (args, ctx) => {
			const { verb, rest } = parseCommand(args);
			if (verb === "invalid") {
				warn(
					ctx,
					"Usage: /jira on|off|toggle|status|bind|clear|show|search|create|sync|transition|context",
				);
				return;
			}

			if (verb === "on") {
				enabled = true;
				info(ctx, "Jira helper ON");
				return;
			}
			if (verb === "off") {
				enabled = false;
				info(ctx, "Jira helper OFF (nudges disabled; commands still work)");
				return;
			}
			if (verb === "toggle") {
				enabled = !enabled;
				info(ctx, `Jira helper ${enabled ? "ON" : "OFF"}`);
				return;
			}
			if (verb === "status") {
				info(
					ctx,
					formatStatus({
						enabled,
						boundKey: state.boundKey,
						lastSyncAt: state.lastSyncAt,
						nudgeEveryNTurns: cfg.nudgeEveryNTurns,
						pendingContextInject: state.pendingContextInject,
					}),
				);
				return;
			}
			if (verb === "clear") {
				clearBind(state);
				info(ctx, "Jira binding cleared");
				return;
			}
			if (verb === "bind") {
				if (!rest || !looksLikeIssueKey(rest)) {
					warn(ctx, "Usage: /jira bind PROJ-123");
					return;
				}
				bindKey(state, rest);
				info(ctx, `Bound ${state.boundKey}`);
				return;
			}

			if (verb === "show") {
				if (!state.boundKey) {
					warn(ctx, "Jira: unbound — /jira bind or /jira search first");
					return;
				}
				await withClient(ctx, async (client) => {
					const raw = await client.callTool("get_jira_issue", { issue_key: state.boundKey });
					const text = toolResultText(raw);
					info(ctx, text.slice(0, 1500) || `(no body for ${state.boundKey})`);
				});
				return;
			}

			if (verb === "search") {
				if (!rest) {
					warn(ctx, "Usage: /jira search <text|jql>");
					return;
				}
				await withClient(ctx, async (client) => {
					const jql = toSearchJql(rest);
					const raw = await client.callTool("search_jira_issues", { jql, max_results: 10 });
					const text = toolResultText(raw);
					let issues: Array<{ key?: string; summary?: string; fields?: { summary?: string } }> = [];
					try {
						const parsed = JSON.parse(text) as {
							issues?: Array<{ key?: string; summary?: string; fields?: { summary?: string } }>;
						};
						issues = parsed.issues ?? [];
					} catch {
						info(ctx, text.slice(0, 1200));
						return;
					}
					if (issues.length === 0) {
						info(ctx, "No issues found");
						return;
					}
					const labels = issues.map((i) => {
						const key = i.key ?? "?";
						const summary = i.summary ?? i.fields?.summary ?? "";
						return `${key} ${summary}`.trim();
					});
					let pick: string | undefined;
					if (ctx.hasUI && typeof ctx.ui.select === "function") {
						pick = (await ctx.ui.select("Bind which issue?", labels)) as string | undefined;
					} else {
						pick = labels[0];
					}
					if (!pick) return;
					const key = pick.split(/\s+/)[0];
					if (!looksLikeIssueKey(key)) {
						warn(ctx, "Could not parse issue key from selection");
						return;
					}
					bindKey(state, key);
					info(ctx, `Bound ${state.boundKey}`);
				});
				return;
			}

			if (verb === "create") {
				await withClient(ctx, async (client) => {
					const projRaw = await client.callTool("get_jira_projects", {});
					const projText = toolResultText(projRaw);
					let projects: Array<{ key?: string; name?: string }> = [];
					try {
						const parsed = JSON.parse(projText) as {
							projects?: Array<{ key?: string; name?: string }>;
						};
						projects = parsed.projects ?? [];
					} catch {
						warn(ctx, "Could not parse project list");
						return;
					}
					if (projects.length === 0) {
						warn(ctx, "No Jira projects available");
						return;
					}
					const projLabels = projects.map((p) => `${p.key} — ${p.name ?? ""}`);
					let projPick: string | undefined;
					if (ctx.hasUI && typeof ctx.ui.select === "function") {
						projPick = (await ctx.ui.select("Project?", projLabels)) as string | undefined;
					} else {
						projPick = projLabels[0];
					}
					if (!projPick) return;
					const projectKey = projPick.split(/\s+—\s+/)[0]?.trim() || projPick.split(/\s+/)[0];

					const singleRaw = await client.callTool("get_single_project", { project_key: projectKey });
					const singleText = toolResultText(singleRaw);
					let issueTypes: Array<{ name?: string; id?: string }> = [];
					try {
						const parsed = JSON.parse(singleText) as {
							issueTypes?: Array<{ name?: string; id?: string }>;
							issue_types?: Array<{ name?: string; id?: string }>;
						};
						issueTypes = parsed.issueTypes ?? parsed.issue_types ?? [];
					} catch {
						/* fall through */
					}
					const typeLabels =
						issueTypes.length > 0
							? issueTypes.map((t) => t.name ?? t.id ?? "Task")
							: ["Task"];
					let typePick: string | undefined;
					if (ctx.hasUI && typeof ctx.ui.select === "function") {
						typePick = (await ctx.ui.select("Issue type?", typeLabels)) as string | undefined;
					} else {
						typePick = typeLabels[0];
					}
					if (!typePick) return;

					let summary = rest;
					if (!summary && ctx.hasUI && typeof ctx.ui.input === "function") {
						summary = ((await ctx.ui.input("Summary?")) as string) ?? "";
					}
					if (!summary?.trim()) {
						warn(ctx, "Usage: /jira create <summary> (or enter when prompted)");
						return;
					}

					const ok = await confirm(
						ctx,
						`Create ${typePick} in ${projectKey}: "${summary.trim()}"?`,
					);
					if (!ok) {
						info(ctx, "Create cancelled");
						return;
					}

					const createRaw = await client.callTool("create_jira_issue", {
						project_key: projectKey,
						issue_type: typePick,
						summary: summary.trim(),
					});
					const createText = toolResultText(createRaw);
					let newKey: string | undefined;
					try {
						const parsed = JSON.parse(createText) as { key?: string; issue_key?: string };
						newKey = parsed.key ?? parsed.issue_key;
					} catch {
						const m = createText.match(/\b([A-Z][A-Z0-9]+-\d+)\b/);
						newKey = m?.[1];
					}
					if (!newKey) {
						warn(ctx, `Create returned no key: ${createText.slice(0, 200)}`);
						return;
					}
					bindKey(state, newKey);
					info(ctx, `Created and bound ${state.boundKey}`);
				});
				return;
			}

			if (verb === "sync") {
				if (!state.boundKey) {
					warn(ctx, "Jira: unbound — cannot sync");
					return;
				}
				const note = rest;
				const body = [
					`Session update from pi (${new Date().toISOString()})`,
					`cwd: ${ctx.cwd}`,
					note ? `note: ${note}` : null,
				]
					.filter(Boolean)
					.join("\n");
				const ok = await confirm(ctx, `Post comment to ${state.boundKey}?`);
				if (!ok) {
					info(ctx, "Sync cancelled");
					return;
				}
				await withClient(ctx, async (client) => {
					await client.callTool("add_jira_comment", {
						issue_key: state.boundKey,
						comment: body,
					});
					state.lastSyncAt = Date.now();
					info(ctx, `Synced comment to ${state.boundKey}`);
				});
				return;
			}

			if (verb === "transition") {
				if (!state.boundKey) {
					warn(ctx, "Jira: unbound — cannot transition");
					return;
				}
				await withClient(ctx, async (client) => {
					const raw = await client.callTool("get_jira_transitions", {
						issue_key: state.boundKey,
					});
					const text = toolResultText(raw);
					let transitions: Array<{ id?: string; name?: string }> = [];
					try {
						const parsed = JSON.parse(text) as {
							transitions?: Array<{ id?: string; name?: string }>;
						};
						transitions = parsed.transitions ?? [];
					} catch {
						warn(ctx, "Could not parse transitions");
						return;
					}
					if (transitions.length === 0) {
						info(ctx, "No transitions available");
						return;
					}
					const labels = transitions.map((t) => `${t.name ?? "?"} (${t.id ?? "?"})`);
					let pick: string | undefined = rest || undefined;
					if (!pick && ctx.hasUI && typeof ctx.ui.select === "function") {
						pick = (await ctx.ui.select("Transition?", labels)) as string | undefined;
					}
					if (!pick && labels.length === 1) pick = labels[0];
					if (!pick) {
						warn(ctx, "Usage: /jira transition <name|id>");
						return;
					}
					const match =
						transitions.find(
							(t) =>
								t.id === pick ||
								t.name?.toLowerCase() === pick.toLowerCase() ||
								`${t.name} (${t.id})` === pick ||
								labels.includes(pick),
						) ??
						transitions.find((t) => pick!.toLowerCase().includes((t.name ?? "").toLowerCase()));
					if (!match?.id) {
						warn(ctx, `No transition matching "${pick}"`);
						return;
					}
					const ok = await confirm(
						ctx,
						`Transition ${state.boundKey} → ${match.name ?? match.id}?`,
					);
					if (!ok) {
						info(ctx, "Transition cancelled");
						return;
					}
					await client.callTool("transition_jira_issue", {
						issue_key: state.boundKey,
						transition_id: match.id,
					});
					info(ctx, `Transitioned ${state.boundKey} → ${match.name ?? match.id}`);
				});
				return;
			}

			if (verb === "context") {
				if (!state.boundKey) {
					warn(ctx, "Jira: unbound — cannot inject context");
					return;
				}
				await withClient(ctx, async (client) => {
					const raw = await client.callTool("get_jira_issue", { issue_key: state.boundKey });
					const text = toolResultText(raw);
					// Stash for one-shot before_agent_start latch (D3).
					(state as SessionStateWithPayload).pendingPayload = [
						"<jira_context>",
						`Bound issue: ${state.boundKey}`,
						text.slice(0, 6000),
						"</jira_context>",
					].join("\n");
					state.pendingContextInject = true;
					info(ctx, `Context queued for ${state.boundKey} (injects on next agent turn)`);
				});
				return;
			}
		},
	});

	pi.on("before_agent_start", async () => {
		if (!state.pendingContextInject) return;
		const payload = (state as SessionStateWithPayload).pendingPayload;
		state.pendingContextInject = false;
		(state as SessionStateWithPayload).pendingPayload = undefined;
		if (!payload) return;
		return {
			message: {
				customType: "jira_context",
				content: payload,
				display: false,
			},
		};
	});

	pi.on("agent_end", (_event, ctx) => {
		state.agentEndCount += 1;
		if (!shouldNudge(enabled, cfg.nudgeEveryNTurns, state.agentEndCount)) return;
		if (!ctx.hasUI) return;
		try {
			ctx.ui.notify(formatNudgeMessage(state), "info");
		} catch {
			/* never block turn */
		}
	});

	pi.on("session_shutdown", async () => {
		try {
			await closeClient();
		} catch {
			/* ignore */
		}
	});
}

type SessionStateWithPayload = ReturnType<typeof createSessionState> & {
	pendingPayload?: string;
};

// Re-exports for tests
export {
	parseCommand,
	sanitizeErrorMessage,
	shouldNudge,
	formatStatus,
	formatNudgeMessage,
	toSearchJql,
	looksLikeIssueKey,
	createSessionState,
	bindKey,
	clearBind,
} from "./helpers.ts";
export { loadConfig } from "./config.ts";
export { setClientForTests, toolResultText } from "./client.ts";
