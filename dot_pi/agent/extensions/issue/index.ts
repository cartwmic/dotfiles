/**
 * issue — standalone work-profile pi extension for multi-provider issue tracking.
 *
 * Supports Jira (MCP client) and GitHub (gh CLI).
 * See README.md.
 */
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import type {
  ExtensionAPI,
  ExtensionCommandContext,
} from "@mariozechner/pi-coding-agent";
import { loadConfig } from "./config.ts";
import {
	buildIssueCreationPrompt,
	formatIssueDraft,
	loadIssueTemplate,
	parseGeneratedIssue,
	parseIssueDraft,
	validateIssueBodyAgainstTemplate,
} from "./creation.ts";
import { effectiveEnabled, saveRuntimeState } from "./state.ts";
import {
  buildMapPrompt,
  buildReducePrompt,
  buildSummaryPrompt,
  extractTranscriptAfter,
  extractTranscriptChunks,
  lastEntryId,
  packChunks,
  TRANSCRIPT_SEP,
  transcriptCharBudget,
} from "./summary.ts";
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

async function confirm(
  ctx: ExtensionCommandContext,
  message: string,
): Promise<boolean> {
	if (!ctx.hasUI || typeof ctx.ui.confirm !== "function") return true;
	try {
		return Boolean(await ctx.ui.confirm("Issue", message));
	} catch {
		return false;
	}
}

type ModelRunResult = { ok: true; text: string } | { ok: false; error: string };

/**
 * Complete a prompt against the CURRENT session model, in-process. Routes
 * extension-registered custom-api providers (e.g. the cursor / claude bridges)
 * through their own streamSimple, since bare pi-ai complete() only knows pi-ai's
 * api registry. This is why the summary/draft model must be the live session
 * model and NOT a child `pi -p` (a child with extensions disabled can't resolve
 * bridge-provided models like cursor/*).
 */
async function runModel(
  ctx: ExtensionCommandContext,
  prompt: string,
): Promise<ModelRunResult> {
	const model = ctx.model as
		| { provider: string; id: string; api: string }
		| undefined;
	if (!model) return { ok: false, error: "no active session model" };
	let apiKey: string | undefined;
	let headers: Record<string, string> | undefined;
	try {
		const auth = await ctx.modelRegistry.getApiKeyAndHeaders(model as never);
		if (auth.ok) {
			apiKey = auth.apiKey;
			headers = auth.headers;
		}
	} catch {
		/* proceed; bridge providers may authenticate internally */
	}
	const context = {
    messages: [
      {
        role: "user",
        content: [{ type: "text", text: prompt }],
        timestamp: Date.now(),
      },
    ],
	};
	// thinkingEnabled:false forces a plain-text completion. Reasoning models
	// (e.g. claude-opus-4-8) are adaptive-thinking and default thinking ON when
	// no thinking param is sent; with our modest maxTokens the model can spend
	// the whole budget on reasoning and return zero answer text. Summaries and
	// drafts never want reasoning output, so disable it explicitly. Non-reasoning
	// models and bridge providers ignore this option.
	const options = {
		apiKey,
		headers,
		maxTokens: 4096,
		thinkingEnabled: false,
		signal: ctx.signal,
	};
	try {
		const cfg = (
			ctx.modelRegistry as unknown as {
        getRegisteredProviderConfig?: (
          p: string,
        ) => { streamSimple?: unknown; api?: string } | undefined;
			}
		).getRegisteredProviderConfig?.(model.provider);
		let res: unknown;
		if (cfg?.streamSimple && cfg.api === model.api) {
			res = await (
        cfg.streamSimple as (
          m: unknown,
          c: unknown,
          o: unknown,
        ) => { result: () => Promise<unknown> }
			)(model, context, options).result();
		} else {
			// Dynamic import keeps @mariozechner/pi-ai (runtime-resolved by pi, not on
			// disk) out of the offline test import graph.
			const { complete } = (await import("@mariozechner/pi-ai")) as {
				complete: (m: unknown, c: unknown, o: unknown) => Promise<unknown>;
			};
			res = await complete(model, context, options);
		}
		const result = res as {
			content?: unknown[];
			stopReason?: string;
			errorMessage?: string;
		};
		const content = result?.content ?? [];
		const text = content
			.filter((c: unknown) => (c as { type?: string })?.type === "text")
			.map((c: unknown) => (c as { text?: string }).text ?? "")
			.join("")
			.trim();
		if (text) return { ok: true, text };
		// No answer text. A completion can end without text for several reasons;
		// the provider records the real cause on the returned assistant message
		// (stopReason "error"/"aborted" carries errorMessage; "length" means the
		// output-token budget was exhausted — often entirely on reasoning for a
		// thinking model like claude-opus-*). Surface that instead of collapsing
		// every outcome into a generic "no text", which is undiagnosable.
		const hadThinking = content.some(
			(c: unknown) => (c as { type?: string })?.type === "thinking",
		);
		if (result?.errorMessage) return { ok: false, error: result.errorMessage };
		const reason = result?.stopReason;
		if (reason === "length") {
			return {
				ok: false,
				error: hadThinking
					? "model exhausted its output-token budget on reasoning before producing any answer text (raise maxTokens or disable thinking for the summary call)"
					: "model hit the output-token limit before producing text",
			};
		}
		if (hadThinking) {
			return { ok: false, error: "model returned only reasoning, no answer text" };
		}
		return {
			ok: false,
			error: reason
				? `model returned no text (stopReason: ${reason})`
				: "model returned no text",
		};
	} catch (e: unknown) {
		return { ok: false, error: e instanceof Error ? e.message : String(e) };
	}
}

/**
 * Produce the checkpoint comment from a transcript, staying within the model's
 * context window. When the transcript fits one request's budget it is a single
 * pass (buildSummaryPrompt). Otherwise it is a map/reduce: the ordered segments
 * are packed into budget-sized groups, each group is condensed to a digest
 * (buildMapPrompt), and the digests are combined into the final comment
 * (buildReducePrompt) — recursively collapsing digests that themselves exceed
 * the budget, so arbitrarily large sessions never re-trigger a context-length
 * error. Any failed sub-call short-circuits with a part-tagged error.
 */
async function summarizeTranscript(
	ctx: ExtensionCommandContext,
	issue: { displayKey: string; title: string; body?: string },
	chunks: string[],
	budgetChars: number,
): Promise<ModelRunResult> {
	const joined = chunks.join(TRANSCRIPT_SEP).trim();
	if (joined.length <= budgetChars) {
		return runModel(ctx, buildSummaryPrompt(issue, joined));
	}
	const groups = packChunks(chunks, budgetChars);
	info(
		ctx,
		`Transcript too large for one pass; summarizing ${chunks.length} segments in ${groups.length} parts, then combining\u2026`,
	);
	const digests: string[] = [];
	for (let i = 0; i < groups.length; i++) {
		const portion = groups[i].join(TRANSCRIPT_SEP);
		const r = await runModel(
			ctx,
			buildMapPrompt(issue, portion, i + 1, groups.length),
		);
		if (!r.ok) {
			return { ok: false, error: `part ${i + 1}/${groups.length}: ${r.error}` };
		}
		digests.push(r.text);
	}
	return reduceDigests(ctx, issue, digests, budgetChars);
}

/**
 * Combine ordered progress digests into the final comment. If the digests do
 * not fit one request, pack them into budget-sized groups, reduce each group to
 * a merged digest, and recurse until a single reduce call fits. buildReducePrompt
 * is reused at every level; its output contract is always "a checkpoint comment",
 * so an intermediate merge of a subset is still well-formed.
 */
async function reduceDigests(
	ctx: ExtensionCommandContext,
	issue: { displayKey: string; title: string; body?: string },
	digests: string[],
	budgetChars: number,
): Promise<ModelRunResult> {
	const joined = digests.join(TRANSCRIPT_SEP).trim();
	if (digests.length <= 1 || joined.length <= budgetChars) {
		return runModel(ctx, buildReducePrompt(issue, digests));
	}
	const groups = packChunks(digests, budgetChars);
	// Guard against a non-converging recursion: if packing cannot reduce the
	// count (single oversized digest already capped by packChunks), fall through
	// to a final reduce rather than looping forever.
	if (groups.length >= digests.length) {
		return runModel(ctx, buildReducePrompt(issue, digests));
	}
	const merged: string[] = [];
	for (let i = 0; i < groups.length; i++) {
		const r = await runModel(ctx, buildReducePrompt(issue, groups[i]));
		if (!r.ok) {
			return { ok: false, error: `merge ${i + 1}/${groups.length}: ${r.error}` };
		}
		merged.push(r.text);
	}
	return reduceDigests(ctx, issue, merged, budgetChars);
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
    issue.body
      ? `  <body>${escapeXml(issue.body.slice(0, 4000))}</body>`
      : null,
		`</issue_context>`,
	]
		.filter(Boolean)
		.join("\n");
}

export default function (pi: ExtensionAPI): void {
	const dir = extensionDir();
	const cfg = loadConfig(dir);
	// Effective on/off: sidecar state.json (runtime, non-chezmoi) wins over config.json.
	const state = createSessionState(
		effectiveEnabled(dir, cfg.behavior.enabled),
		cfg.behavior.nudgeEveryNTurns,
	);

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
      const {
        verb,
        provider: explicitProvider,
        rest,
        rawRest,
      } = parseCommand(args);

			// Persist the on/off state to state.json, then update memory only on
			// success so memory and disk never diverge. Returns false on I/O failure.
			const persistEnabled = (value: boolean): boolean => {
				try {
					saveRuntimeState(dir, { enabled: value });
					state.enabled = value;
					return true;
				} catch (err) {
					warn(ctx, `Could not persist toggle: ${sanitizeErrorMessage(err)}`);
					return false;
				}
			};

			if (verb === "invalid") {
				warn(
					ctx,
					"Usage: /issue on|off|toggle|status|bind|clear|show|search|create|sync|transition|context",
				);
				return;
			}

			// --- Global toggles ---
			if (verb === "on") {
				if (persistEnabled(true)) info(ctx, "Issue helper ON");
				return;
			}
			if (verb === "off") {
        if (persistEnabled(false))
          info(ctx, "Issue helper OFF (nudges disabled; commands still work)");
				return;
			}
			if (verb === "toggle") {
        if (persistEnabled(!state.enabled))
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
          for (const name of providerNames)
            clearBind(getProviderState(state, name));
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
            info(
              ctx,
              `${issue.displayKey}: ${issue.title} [${issue.status}] ${issue.url}`,
            );
					}
				} else {
					for (const name of providerNames) {
						const ps = getProviderState(state, name);
						if (!ps.boundKey) continue;
            const issue = await withProvider(ctx, name, (p) =>
              p.getIssue(ps.boundKey!),
            );
						if (issue) {
              info(
                ctx,
                `${issue.displayKey}: ${issue.title} [${issue.status}] ${issue.url}`,
              );
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
          const result = await withProvider(ctx, name, (p) =>
            p.searchIssues(rest),
          );
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
            const labels = result.issues.map(
              (i) => `${i.displayKey}: ${i.title}`,
            );
            const pick = (await ctx.ui.select("Bind issue?", labels)) as
              | string
              | undefined;
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
				// Generated content must be reviewed before it can mutate an issue tracker.
				if (
					!ctx.hasUI ||
					typeof ctx.ui.editor !== "function" ||
					typeof ctx.ui.confirm !== "function"
				) {
          warn(
            ctx,
            "Issue creation needs interactive UI to review the generated draft.",
          );
					return;
				}
				if (!ctx.model) {
					warn(ctx, "No active session model to draft with.");
					return;
				}

				let template: string;
				try {
					template = loadIssueTemplate(dir);
				} catch (err) {
					warn(ctx, `Cannot load issue template: ${sanitizeErrorMessage(err)}`);
					return;
				}

				let target = explicitProvider;
				if (!target && providerNames.length === 1) {
					target = providerNames[0];
        } else if (
          !target &&
          providerNames.length > 1 &&
          typeof ctx.ui.select === "function"
        ) {
          target = (await ctx.ui.select(
            "Create issue with which provider?",
            providerNames,
          )) as string | undefined;
					if (!target) return;
				}
				if (!target) {
          warn(
            ctx,
            "No issue provider available. Specify jira or github after /issue create.",
          );
					return;
				}
				if (!providers.has(target)) {
					warn(ctx, `Issue: ${target} provider is not available`);
					return;
				}

				const doCreate = async (name: string) => {
					let userInput = rawRest.trim();
					const extra: Record<string, unknown> = {};
					if (name === "jira") {
						const jiraPs = getProviderState(state, "jira");
						if (jiraPs.boundKey) {
							const project = jiraPs.boundKey.split("-")[0];
							if (project) extra.project = project;
						} else {
							const words = userInput.split(/\s+/).filter(Boolean);
							const project = words[0];
							if (!project || !/^[A-Z][A-Z0-9]{1,9}$/.test(project)) {
								warn(
									ctx,
									"Jira project required. Bind a Jira issue or use /issue create jira PROJ [input].",
								);
								return;
							}
							extra.project = project;
							userInput = words.slice(1).join(" ");
						}
					}

					const transcript = extractTranscriptAfter(
						ctx.sessionManager.getEntries() as unknown[],
						null,
					);
					if (!userInput && !transcript) {
            warn(
              ctx,
              "Nothing to draft from. Add input after /issue create or start from a session.",
            );
						return;
					}

          info(
            ctx,
            `Drafting ${name} issue with ${ctx.model.provider}/${ctx.model.id}\u2026`,
          );
					const generated = await runModel(
						ctx,
            buildIssueCreationPrompt({
              provider: name,
              template,
              transcript,
              userInput,
            }),
					);
					if (!generated.ok) {
            warn(
              ctx,
              `Issue draft failed: ${sanitizeErrorMessage(generated.error)}`,
            );
						return;
					}

					let draft: ReturnType<typeof parseGeneratedIssue>;
					try {
						draft = parseGeneratedIssue(generated.text);
						validateIssueBodyAgainstTemplate(draft.body, template);
					} catch (err) {
						warn(ctx, `Issue draft failed: ${sanitizeErrorMessage(err)}`);
						return;
					}

					let edited: string | undefined;
					try {
						edited = await ctx.ui.editor(
							`Review ${name} issue draft (# title, then template body)`,
							formatIssueDraft(draft),
						);
					} catch {
						return;
					}
					if (edited === undefined) return;
					try {
						draft = parseIssueDraft(edited);
						validateIssueBodyAgainstTemplate(draft.body, template);
					} catch (err) {
						warn(ctx, `Invalid issue draft: ${sanitizeErrorMessage(err)}`);
						return;
					}

          const location =
            name === "jira" && extra.project ? ` in ${extra.project}` : "";
					const issue = await withProvider(ctx, name, async (p) => {
            if (
              !(await confirm(
                ctx,
                `Create ${name} issue${location}: "${draft.title}"?`,
              ))
            ) {
							return null;
						}
            return await p.createIssue({
              title: draft.title,
              body: draft.body,
              ...extra,
            });
					});
					if (issue) {
						bindKey(getProviderState(state, name), issue.key);
						info(ctx, `Created and bound ${issue.displayKey}: ${issue.url}`);
					}
				};

				await doCreate(target);
				return;
			}

			// --- Sync ---
			// No args -> auto-summarize session progress since last checkpoint.
			// With args -> post the given text verbatim (original behavior).
			if (verb === "sync") {
				const checkpoint = rawRest.trim() === "";
				if (checkpoint) {
					// Fail closed: a checkpoint posts unvetted model output, so it
					// REQUIRES both an interactive editor (review) AND confirm (final
					// gate) before posting. Never auto-post in headless/no-UI mode, and
					// never fall through to the auto-true confirm (Decision 7 +
					// no-auto-mutate).
					if (
						!ctx.hasUI ||
						typeof ctx.ui.editor !== "function" ||
						typeof ctx.ui.confirm !== "function"
					) {
						warn(
							ctx,
							"Checkpoint summary needs interactive UI to review before posting. Use /issue sync <note> for a headless comment.",
						);
						return;
					}
					if (!ctx.model) {
            warn(
              ctx,
              "No active session model to summarize with. Use /issue sync <note> instead.",
            );
						return;
					}
				}

				// Resolve the comment body + the anchor to advance to on success. null
				// => skip/cancel. The checkpoint anchor is the moment the transcript is
				// snapshotted (NOT post-completion time), so entries appended during the
				// multi-minute summary/editor/confirm window are covered by the NEXT
				// checkpoint instead of being skipped (Decision 2, no lost entries).
				// The bound key + entry cursor are captured BEFORE any await and used
				// throughout, so a concurrent /issue bind|clear during an in-flight
				// (async, multi-minute) checkpoint can't cause issue A's summary to be
				// posted to issue B, and can't move the anchor backward.
				const resolveBody = async (
					name: string,
					boundKey: string,
					sinceEntryId: string | null,
				): Promise<{ body: string; anchorEntryId: string | null } | null> => {
					if (!checkpoint) {
            const anchorEntryId = lastEntryId(
              ctx.sessionManager.getEntries() as unknown[],
            );
						return { body: rawRest, anchorEntryId };
					}
          const issue = await withProvider(ctx, name, (p) =>
            p.getIssue(boundKey),
          );
					if (!issue) return null;
					const entries = ctx.sessionManager.getEntries() as unknown[];
					const anchorEntryId = lastEntryId(entries);
					const chunks = extractTranscriptChunks(entries, sinceEntryId);
					const budgetChars = transcriptCharBudget(ctx.model?.contextWindow);
          info(
            ctx,
            `Summarizing ${name} ${boundKey} with ${ctx.model?.provider}/${ctx.model?.id}\u2026`,
          );
          const res = await summarizeTranscript(
            ctx,
            issue,
            chunks,
            budgetChars,
          );
					if (!res.ok) {
            warn(
              ctx,
              `Summary failed (${name}): ${sanitizeErrorMessage(res.error)}`,
            );
						return null;
					}
					// Editor guaranteed present (fail-closed guard above). Wrap so an
					// editor rejection fails closed (no post) rather than throwing.
					let edited: string | undefined;
					try {
						edited = await ctx.ui.editor(
							`Checkpoint comment for ${name} ${boundKey} (edit, then submit)`,
							res.text,
						);
					} catch {
						return null;
					}
					if (edited === undefined) return null; // cancelled
					const body = edited.trim();
					return body ? { body, anchorEntryId } : null;
				};

				const doSync = async (name: string) => {
					const ps = getProviderState(state, name);
					const boundKey = ps.boundKey;
					if (!boundKey) return false;
					// Refuse overlapping syncs for the same provider (avoids double-post
					// and cursor races between two concurrent /issue sync invocations).
					if (ps.syncing) {
						warn(ctx, `Sync already in progress for ${name}`);
						return false;
					}
					// Capture the binding generation + cursor before any await; a
					// concurrent bind/clear (even to the same key) bumps the generation
					// and invalidates this in-flight checkpoint.
					const gen = ps.bindGeneration;
					const sinceEntryId = ps.lastSyncEntryId;
					ps.syncing = true;
					try {
						const resolved = await resolveBody(name, boundKey, sinceEntryId);
						if (resolved == null) return false;
						if (ps.bindGeneration !== gen) {
							warn(ctx, `Skipped ${name}: binding changed during sync`);
							return false;
						}
						const { body, anchorEntryId } = resolved;
            const preview =
              body.length > 120 ? `${body.slice(0, 117)}...` : body;
						const ok = await withProvider(ctx, name, async (p) => {
              if (
                !(await confirm(
                  ctx,
                  `Comment on ${name} ${boundKey}: "${preview}"?`,
                ))
              )
								return false;
							if (ps.bindGeneration !== gen) {
								warn(ctx, `Skipped ${name}: binding changed during sync`);
								return false; // re-check post-confirm
							}
							await p.addComment(boundKey, body);
							return true;
						});
						// Advance the cursor ONLY if the binding is still the one we posted
						// to. A rebind during the addComment round-trip resets the cursor;
						// the comment still posted to the correct captured boundKey, but we
						// must not stamp the now-foreign binding with this issue's cursor.
						if (ok && ps.bindGeneration === gen) {
							ps.lastSyncAt = Date.now();
							ps.lastSyncEntryId = anchorEntryId;
							ps.pendingContextInject = false;
							info(ctx, `Synced to ${name}: ${boundKey}`);
						}
						return ok;
					} finally {
						ps.syncing = false;
					}
				};

				if (explicitProvider) {
					await doSync(explicitProvider);
				} else {
					// Warn about unbound only when NOTHING is bound — not when syncs were
					// cancelled/declined/failed (those already surface their own message).
          const bound = providerNames.filter(
            (n) => getProviderState(state, n).boundKey,
          );
					if (bound.length === 0) {
						warn(ctx, "No issues bound. /issue bind <key>");
					} else {
						for (const name of bound) await doSync(name);
					}
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
        const boundKey = ps.boundKey;
        const bindGeneration = ps.bindGeneration;
        const bindingChanged = () =>
          ps.bindGeneration !== bindGeneration || ps.boundKey !== boundKey;
				const transitions = await withProvider(ctx, "jira", (p) =>
          p.listTransitions!(boundKey),
				);
				if (!transitions) return;
        if (bindingChanged()) {
          warn(
            ctx,
            "Skipped Jira transition: binding changed while loading transitions",
          );
          return;
        }
				if (transitions.length === 0) {
					info(ctx, "No transitions available");
					return;
				}

				let pick = rest || undefined;
				if (!pick && ctx.hasUI && typeof ctx.ui.select === "function") {
					const labels = transitions.map((t) => `${t.name} (${t.id})`);
          pick = (await ctx.ui.select("Transition?", labels)) as
            | string
            | undefined;
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
          transitions.find((t) =>
            pick!.toLowerCase().includes(t.name.toLowerCase()),
          );
				if (!match) {
					warn(
						ctx,
						`No transition matching "${pick}". Available: ${transitions.map((t) => t.name).join(", ")}`,
					);
					return;
				}

        if (bindingChanged()) {
          warn(
            ctx,
            "Skipped Jira transition: binding changed during selection",
          );
          return;
        }
				const ok = await withProvider(ctx, "jira", async (p) => {
          if (!(await confirm(ctx, `Transition ${boundKey} → ${match.name}?`)))
            return false;
          if (bindingChanged()) {
            warn(
              ctx,
              "Skipped Jira transition: binding changed during confirmation",
            );
						return false;
          }
          await p.transitionIssue!(boundKey, match.id);
					return true;
				});
        if (ok) info(ctx, `Transitioned ${boundKey} → ${match.name}`);
				return;
			}

			// --- Context ---
			if (verb === "context") {
        const queueOne = async (name: string): Promise<boolean | null> => {
					const ps = getProviderState(state, name);
					if (!ps.boundKey) return false;
          const boundKey = ps.boundKey;
          const bindGeneration = ps.bindGeneration;
          const issue = await withProvider(ctx, name, (p) =>
            p.getIssue(boundKey),
          );
          if (
            ps.bindGeneration !== bindGeneration ||
            ps.boundKey !== boundKey
          ) {
            warn(
              ctx,
              `Skipped ${name} context: binding changed while loading issue`,
            );
            return null;
          }
					if (issue) {
						ps.pendingPayload = buildContextPayload(issue);
						ps.pendingContextInject = true;
					}
					return !!issue;
				};

				if (explicitProvider) {
          const queued = await queueOne(explicitProvider);
          if (queued === true) {
						info(ctx, `Context queued for ${explicitProvider}`);
          } else if (queued === false) {
						warn(ctx, `No ${explicitProvider} issue bound`);
					}
				} else {
					let any = false;
          let changed = false;
					for (const name of providerNames) {
            const queued = await queueOne(name);
            if (queued === true) any = true;
            if (queued === null) changed = true;
					}
          if (any) info(ctx, "Context queued for all stable bound issues");
          else if (!changed) warn(ctx, "No issues bound");
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
    if (
      !shouldNudge(state.enabled, state.nudgeEveryNTurns, state.agentEndCount)
    )
      return;
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
export {
	buildIssueCreationPrompt,
	formatIssueDraft,
	loadIssueTemplate,
	parseGeneratedIssue,
	parseIssueDraft,
	validateIssueBodyAgainstTemplate,
} from "./creation.ts";
export {
  buildMapPrompt,
  buildReducePrompt,
  buildSummaryPrompt,
  CHARS_PER_TOKEN,
  extractTranscriptAfter,
  extractTranscriptChunks,
  lastEntryId,
  packChunks,
  TRANSCRIPT_BUDGET_FRACTION,
  TRANSCRIPT_SEP,
  transcriptCharBudget,
} from "./summary.ts";
export {
  effectiveEnabled,
  loadRuntimeState,
  saveRuntimeState,
} from "./state.ts";
export { setJiraClientForTests } from "./providers/jira.ts";
