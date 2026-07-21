/**
 * issue — standalone work-profile pi extension for multi-provider issue tracking.
 *
 * Supports Jira (MCP client) and GitHub (gh CLI).
 * See README.md.
 */
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI, ExtensionCommandContext } from "@mariozechner/pi-coding-agent";
import { loadConfig } from "./config.ts";
import { closeJiraClient, JiraProvider } from "./providers/jira.ts";
import { GitHubProvider } from "./providers/github.ts";
import type { Issue, IssueProvider } from "./providers/types.ts";
import {
	bindKey,
	clearBind,
	createSessionState,
	detectProviderFromKey,
	formatNudgeMessage,
	formatStatus,
	getProviderState,
	parseCommand,
	sanitizeErrorMessage,
	shouldNudge,
	type ProviderBindState,
	type SessionState,
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
		return Boolean(await ctx.ui.confirm("Issue", message));
	} catch {
		return false;
	}
}

function escapeXml(str: string): string {
	return str
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;");
}

function buildContextPayload(issue: Issue): string {
	return [
		`<issue_context provider="${escapeXml(issue.provider)}">`,
		`  <key>${escapeXml(issue.displayKey)}</key>`,
		`  <status>${escapeXml(issue.status)}</status>`,
		`  <url>${escapeXml(issue.url)}</url>`,
		`  <title>${escapeXml(issue.title)}</title>`,
		issue.body ? `  <body>${escapeXml(issue.body.slice(0, 4000))}</body>` : null,
		`</issue_context>`,
	]
		.filter(Boolean)
		.join("\n");
}

export default function (pi: ExtensionAPI): void {
	const dir = extensionDir();
	const cfg = loadConfig(dir);
	const state = createSessionState(cfg.behavior.enabled, cfg.behavior.nudgeEveryNTurns);

	// Provider registry
	const providers = new Map<string, IssueProvider>();
	const jira = new JiraProvider(cfg.jira);
	const github = new GitHubProvider();
	if (jira.isAvailable) providers.set("jira", jira);
	if (github.isAvailable) providers.set("github", github);
	const providerNames = Array.from(providers.keys());

	async function withProvider<T>(
		ctx: ExtensionCommandContext,
		name: string,
		fn: (p: IssueProvider) => Promise<T>,
	): Promise<T | undefined> {
		const p = providers.get(name);
		if (!p) {
			warn(ctx, `Issue: ${name} provider is not available`);
			return undefined;
		}
		try {
			return await fn(p);
		} catch (err) {
			warn(ctx, `Issue (${name}): ${sanitizeErrorMessage(err)}`);
			return undefined;
		}
	}

	pi.registerCommand("issue", {
		description:
			"Issue tracking helper (on|off|toggle|status|bind|clear|show|search|create|sync|transition|context)",
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
			const { verb, provider: explicitProvider, rest } = parseCommand(args);

			if (verb === "invalid") {
				warn(
					ctx,
					"Usage: /issue on|off|toggle|status|bind|clear|show|search|create|sync|transition|context",
				);
				return;
			}

			// --- Global toggles ---
			if (verb === "on") {
				state.enabled = true;
				info(ctx, "Issue helper ON");
				return;
			}
			if (verb === "off") {
				state.enabled = false;
				info(ctx, "Issue helper OFF (nudges disabled; commands still work)");
				return;
			}
			if (verb === "toggle") {
				state.enabled = !state.enabled;
				info(ctx, `Issue helper ${state.enabled ? "ON" : "OFF"}`);
				return;
			}

			// --- Status ---
			if (verb === "status") {
				const providerStates = providerNames.map((name) => {
					const ps = getProviderState(state, name);
					return { name, boundKey: ps.boundKey, lastSyncAt: ps.lastSyncAt };
				});
				info(
					ctx,
					formatStatus({
						enabled: state.enabled,
						providerStates,
						nudgeEveryNTurns: state.nudgeEveryNTurns,
					}),
				);
				return;
			}

			// --- Bind ---
			if (verb === "bind") {
				if (!rest) {
					warn(ctx, "Usage: /issue bind <key> or /issue bind <provider> <key>");
					return;
				}
				let target = explicitProvider ?? detectProviderFromKey(rest);
				if (!target) {
					warn(
						ctx,
						`Cannot detect provider from "${rest}". Use /issue bind jira PROJ-123 or /issue bind github 123`,
					);
					return;
				}
				if (!providers.has(target)) {
					warn(ctx, `Issue: ${target} provider is not available`);
					return;
				}
				const ps = getProviderState(state, target);
				bindKey(ps, rest);
				info(ctx, `Bound ${target}: ${rest}`);
				return;
			}

			// --- Clear ---
			if (verb === "clear") {
				if (explicitProvider) {
					clearBind(getProviderState(state, explicitProvider));
					info(ctx, `Cleared ${explicitProvider} bind`);
				} else {
					for (const name of providerNames) clearBind(getProviderState(state, name));
					info(ctx, "Cleared all binds");
				}
				return;
			}

			// --- Show ---
			if (verb === "show") {
				if (explicitProvider) {
					const ps = getProviderState(state, explicitProvider);
					if (!ps.boundKey) {
						warn(ctx, `No ${explicitProvider} issue bound`);
						return;
					}
					const issue = await withProvider(ctx, explicitProvider, (p) =>
						p.getIssue(ps.boundKey!),
					);
					if (issue) {
						info(ctx, `${issue.displayKey}: ${issue.title} [${issue.status}] ${issue.url}`);
					}
				} else {
					for (const name of providerNames) {
						const ps = getProviderState(state, name);
						if (!ps.boundKey) continue;
						const issue = await withProvider(ctx, name, (p) => p.getIssue(ps.boundKey!));
						if (issue) {
							info(ctx, `${issue.displayKey}: ${issue.title} [${issue.status}] ${issue.url}`);
						}
					}
				}
				return;
			}

			// --- Search ---
			if (verb === "search") {
				if (!rest) {
					warn(ctx, "Usage: /issue search [provider] <query>");
					return;
				}
				const searchOne = async (name: string) => {
					const result = await withProvider(ctx, name, (p) => p.searchIssues(rest));
					if (!result) return;
					const lines = result.issues.map(
						(i, idx) => `${idx + 1}. ${i.displayKey}: ${i.title} [${i.status}]`,
					);
					info(ctx, `${name} (${result.total}):\n${lines.join("\n")}`);

					// Interactive select when targeting a single provider
					if (
						explicitProvider &&
						result.issues.length > 0 &&
						ctx.hasUI &&
						typeof ctx.ui.select === "function"
					) {
						const labels = result.issues.map((i) => `${i.displayKey}: ${i.title}`);
						const pick = (await ctx.ui.select("Bind issue?", labels)) as string | undefined;
						if (pick) {
							const idx = labels.indexOf(pick);
							if (idx >= 0) {
								const chosen = result.issues[idx];
								bindKey(getProviderState(state, name), chosen.key);
								info(ctx, `Bound ${name}: ${chosen.displayKey}`);
							}
						}
					}
				};

				if (explicitProvider) {
					await searchOne(explicitProvider);
				} else {
					for (const name of providerNames) await searchOne(name);
				}
				return;
			}

			// --- Create ---
			if (verb === "create") {
				const summary = rest || "New issue";
				const doCreate = async (name: string) => {
					let createSummary = summary;
					const extra: Record<string, unknown> = {};
					if (name === "jira") {
						const jiraPs = getProviderState(state, "jira");
						if (jiraPs.boundKey) {
							// Bound: use bound key's project, don't strip prefix from summary
							const project = jiraPs.boundKey.split("-")[0];
							if (project) extra.project = project;
						} else {
							// Unbound: parse project prefix from summary
							const firstWord = summary.split(/\s+/)[0];
							const looksLikeProject = /^[A-Z][A-Z0-9]{1,9}$/.test(firstWord);
							if (looksLikeProject) {
								extra.project = firstWord;
								const restWords = summary.split(/\s+/).slice(1);
								createSummary = restWords.join(" ") || "New issue";
							}
						}
					}
					const issue = await withProvider(ctx, name, async (p) => {
						const confirmMsg =
							name === "jira" && extra.project
								? `Create ${name} issue in ${extra.project}: "${createSummary}"?`
								: `Create ${name} issue: "${createSummary}"?`;
						if (!(await confirm(ctx, confirmMsg))) return null;
						return await p.createIssue({ title: createSummary, ...extra });
					});
					if (issue) {
						bindKey(getProviderState(state, name), issue.key);
						info(ctx, `Created and bound ${issue.displayKey}: ${issue.url}`);
					}
				};

				if (explicitProvider) {
					await doCreate(explicitProvider);
				} else if (providerNames.length === 1) {
					await doCreate(providerNames[0]);
				} else {
					warn(
						ctx,
						"Multiple providers. Specify: /issue create jira <summary> or /issue create github <summary>",
					);
				}
				return;
			}

			// --- Sync ---
			if (verb === "sync") {
				const note = rest || "Sync from pi session";
				const doSync = async (name: string) => {
					const ps = getProviderState(state, name);
					if (!ps.boundKey) return false;
					const ok = await withProvider(ctx, name, async (p) => {
						if (!(await confirm(ctx, `Comment on ${name} ${ps.boundKey}: "${note}"?`)))
							return false;
						await p.addComment(ps.boundKey!, note);
						return true;
					});
					if (ok) {
						ps.lastSyncAt = Date.now();
						ps.pendingContextInject = false;
						info(ctx, `Synced to ${name}: ${ps.boundKey}`);
					}
					return ok;
				};

				if (explicitProvider) {
					await doSync(explicitProvider);
				} else {
					let any = false;
					for (const name of providerNames) {
						if (await doSync(name)) any = true;
					}
					if (!any) warn(ctx, "No issues bound. /issue bind <key>");
				}
				return;
			}

			// --- Transition ---
			if (verb === "transition") {
				let target = explicitProvider;
				if (!target) {
					if (providers.has("jira")) target = "jira";
					else {
						warn(ctx, "Transitions only supported for Jira");
						return;
					}
				}
				if (target !== "jira") {
					warn(ctx, "Transitions only supported for Jira");
					return;
				}
				const ps = getProviderState(state, "jira");
				if (!ps.boundKey) {
					warn(ctx, "No Jira issue bound. /issue bind jira <key>");
					return;
				}
				const transitions = await withProvider(ctx, "jira", (p) =>
					p.listTransitions!(ps.boundKey!),
				);
				if (!transitions) return;
				if (transitions.length === 0) {
					info(ctx, "No transitions available");
					return;
				}

				let pick = rest || undefined;
				if (!pick && ctx.hasUI && typeof ctx.ui.select === "function") {
					const labels = transitions.map((t) => `${t.name} (${t.id})`);
					pick = (await ctx.ui.select("Transition?", labels)) as string | undefined;
				}
				if (!pick && transitions.length === 1) pick = transitions[0].name;
				if (!pick) {
					const lines = transitions.map((t) => `- ${t.name} (id: ${t.id})`);
					info(ctx, `Available transitions:\n${lines.join("\n")}`);
					return;
				}

				const match =
					transitions.find(
						(t) =>
							t.id === pick ||
							t.name.toLowerCase() === pick!.toLowerCase() ||
							`${t.name} (${t.id})` === pick,
					) ??
					transitions.find((t) => pick!.toLowerCase().includes(t.name.toLowerCase()));
				if (!match) {
					warn(
						ctx,
						`No transition matching "${pick}". Available: ${transitions.map((t) => t.name).join(", ")}`,
					);
					return;
				}

				const ok = await withProvider(ctx, "jira", async (p) => {
					if (!(await confirm(ctx, `Transition ${ps.boundKey} → ${match.name}?`)))
						return false;
					await p.transitionIssue!(ps.boundKey!, match.id);
					return true;
				});
				if (ok) info(ctx, `Transitioned ${ps.boundKey} → ${match.name}`);
				return;
			}

			// --- Context ---
			if (verb === "context") {
				const queueOne = async (name: string) => {
					const ps = getProviderState(state, name);
					if (!ps.boundKey) return false;
					const issue = await withProvider(ctx, name, (p) => p.getIssue(ps.boundKey!));
					if (issue) {
						ps.pendingPayload = buildContextPayload(issue);
						ps.pendingContextInject = true;
					}
					return !!issue;
				};

				if (explicitProvider) {
					if (await queueOne(explicitProvider)) {
						info(ctx, `Context queued for ${explicitProvider}`);
					} else {
						warn(ctx, `No ${explicitProvider} issue bound`);
					}
				} else {
					let any = false;
					for (const name of providerNames) {
						if (await queueOne(name)) any = true;
					}
					if (any) info(ctx, "Context queued for all bound issues");
					else warn(ctx, "No issues bound");
				}
				return;
			}
		},
	});

	// Inject queued context before agent starts
	pi.on("before_agent_start", async () => {
		const payloads: string[] = [];
		for (const [name, ps] of state.providers) {
			if (!ps.pendingContextInject) continue;
			ps.pendingContextInject = false;
			if (ps.pendingPayload) {
				payloads.push(ps.pendingPayload);
				ps.pendingPayload = undefined;
			}
		}
		if (payloads.length === 0) return;
		return {
			message: {
				customType: "issue_context",
				content: payloads.join("\n\n"),
				display: false,
			},
		};
	});

	// Nudges on agent_end
	pi.on("agent_end", (_event, ctx) => {
		state.agentEndCount++;
		if (!shouldNudge(state.enabled, state.nudgeEveryNTurns, state.agentEndCount)) return;
		if (!ctx.hasUI) return;
		try {
			ctx.ui.notify(formatNudgeMessage(state, providerNames), "info");
		} catch {
			/* never block turn */
		}
	});

	// Cleanup
	pi.on("session_shutdown", async () => {
		try {
			await closeJiraClient();
		} catch {
			/* ignore */
		}
	});
}

// Re-exports for tests
export {
	bindKey,
	clearBind,
	createSessionState,
	detectProviderFromKey,
	formatNudgeMessage,
	formatStatus,
	getProviderState,
	parseCommand,
	sanitizeErrorMessage,
	shouldNudge,
} from "./helpers.ts";
export { loadConfig } from "./config.ts";
export { setJiraClientForTests } from "./providers/jira.ts";
