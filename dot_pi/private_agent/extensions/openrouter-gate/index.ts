/**
 * openrouter-gate — pi extension: OpenRouter default-OFF, with a persistent
 * on/off toggle and a fail-closed per-model allowlist.
 *
 * Auth still uses absence: the API key lives in auth.json as
 * "openrouter-stashed" (invisible to the registry). `/openrouter on` injects
 * it as a runtime credential + OPENROUTER_API_KEY for subagents. The enabled
 * flag is persisted in this extension's config.json so new sessions stay on
 * until `/openrouter off`.
 *
 * Catalog: pi-openrouter-plus (and the builtin provider) dump the live
 * OpenRouter list. This extension re-registers only allowlisted models via
 * `pi.registerProvider("openrouter", { models })`, which merges over plus's
 * stream/headers. Empty allowlist or enabled=false registers zero models.
 * `/openrouter allow` and `/openrouter deny` edit the allowlist from a
 * searchable picker (live OpenRouter /models, no key required).
 *
 * Plus load-order: packages load after ~/.pi/agent/extensions, and plus
 * re-syncs on session_start *after* this handler. Re-filter on
 * resources_discover, before_agent_start, and model_select.
 *
 * Hindsight rerank/embedding is unaffected: its OpenRouter key lives
 * server-side on hindsight-api, not in pi's auth.json.
 */
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import {
	type CatalogModel,
	type OpenRouterGateConfig,
	buildAllowedModels,
	describeConfig,
	isProviderOpen,
	loadConfig,
	saveConfig,
} from "./config.ts";
import {
	type PickerModel,
	addAllowedModel,
	commandCompletions,
	fetchOpenRouterModels,
	getCachedPickerModels,
	parseCommand,
	pickerItemsExcluding,
	rememberPickerModels,
	removeAllowedModel,
} from "./catalog.ts";

const PROVIDER = "openrouter";
const STASH_ID = "openrouter-stashed";
const ENV_VAR = "OPENROUTER_API_KEY";

export function defaultAuthPath(): string {
	return path.join(os.homedir(), ".pi", "agent", "auth.json");
}

export function defaultConfigPath(): string {
	return path.join(path.dirname(fileURLToPath(import.meta.url)), "config.json");
}

export interface StashState {
	/** API key from the stash entry, when present and well-formed. */
	key?: string;
	/** true ⇒ "openrouter-stashed" entry exists in auth.json. */
	stashPresent: boolean;
	/** true ⇒ a LIVE "openrouter" entry exists ⇒ gate is bypassed. */
	liveEntryPresent: boolean;
	/** Read/parse failure detail, if any. */
	error?: string;
}

/** Pure read of auth.json stash + live-entry state. Never throws. */
export function readStash(
	deps: { readFile?: (p: string) => string; authPath?: string } = {},
): StashState {
	const readFile = deps.readFile ?? ((p) => fs.readFileSync(p, "utf-8"));
	const authPath = deps.authPath ?? defaultAuthPath();
	try {
		const json = JSON.parse(readFile(authPath)) as Record<string, unknown>;
		const liveEntryPresent = Object.hasOwn(json, PROVIDER);
		const entry = json[STASH_ID] as { key?: unknown } | undefined;
		const stashPresent = entry !== undefined;
		const key = typeof entry?.key === "string" && entry.key.length > 0 ? entry.key : undefined;
		return { key, stashPresent, liveEntryPresent };
	} catch (e) {
		return {
			stashPresent: false,
			liveEntryPresent: false,
			error: e instanceof Error ? e.message : String(e),
		};
	}
}

export type Subcommand = "on" | "off" | "status" | "reload" | "help" | "allow" | "deny";

/** Parse the /openrouter argument string. Unknown/empty ⇒ help/status. */
export function parseSubcommand(args: string): Subcommand {
	return parseCommand(args).kind;
}

interface RuntimeLike {
	setRuntimeApiKey: (providerId: string, apiKey: string, opts?: unknown) => Promise<void>;
	removeRuntimeApiKey: (providerId: string) => Promise<void>;
}

/**
 * Reach the ModelRuntime behind the extension-facing ModelRegistry facade.
 * `runtime` is a public field on the facade but not part of the documented
 * extension surface — validate shape and fail soft if pi internals change.
 */
function getRuntime(ctx: unknown): RuntimeLike | undefined {
	const rt = (ctx as { modelRegistry?: { runtime?: unknown } })?.modelRegistry?.runtime as
		| Partial<RuntimeLike>
		| undefined;
	if (
		rt &&
		typeof rt.setRuntimeApiKey === "function" &&
		typeof rt.removeRuntimeApiKey === "function"
	) {
		return rt as RuntimeLike;
	}
	return undefined;
}

function getOpenRouterModels(ctx: unknown): CatalogModel[] {
	const getAll = (ctx as { modelRegistry?: { getAll?: () => unknown } })?.modelRegistry?.getAll;
	if (typeof getAll !== "function") return [];
	const all = getAll();
	if (!Array.isArray(all)) return [];
	const models: CatalogModel[] = [];
	for (const entry of all) {
		if (!entry || typeof entry !== "object") continue;
		const model = entry as Partial<CatalogModel> & { provider?: unknown };
		if (model.provider !== PROVIDER || typeof model.id !== "string" || model.id.length === 0) continue;
		models.push(model as CatalogModel);
	}
	return models;
}

export function catalogSignature(
	config: OpenRouterGateConfig,
	catalogIds: readonly string[],
	registeredIds: readonly string[],
): string {
	return `${config.enabled}\0${config.allowedModels.join("\n")}\0${catalogIds.join("\n")}\0${registeredIds.join("\n")}`;
}

const MISSING_STASH_WARNING =
	`⚠ No "${STASH_ID}" entry in auth.json — cannot enable OpenRouter. ` +
	`If it was there before, pi may have rewritten auth.json (login/logout) and dropped the ` +
	`unknown key. Re-stash the API key as {"${STASH_ID}": {"type": "api_key", "key": "sk-or-..."}}.`;

const LIVE_ENTRY_WARNING =
	`⚠ A live "${PROVIDER}" entry exists in auth.json — auth is always-on for every session ` +
	`and subagent. Rename it to "${STASH_ID}" to restore default-off. The allowlist still applies.`;

const EMPTY_ALLOWLIST_WARNING =
	"⚠ OpenRouter allowlist is empty — fail-closed. Add model ids to this extension's config.json.";

export default function (pi: ExtensionAPI): void {
	const configPath = defaultConfigPath();
	let config = loadConfig(configPath);
	let keyInjected = false;
	let lastCatalogSignature = "";

	function applyCatalog(ctx: unknown): void {
		try {
			const catalog = getOpenRouterModels(ctx);
			rememberPickerModels(catalog);
			const models = isProviderOpen(config) ? buildAllowedModels(catalog, config.allowedModels) : [];
			const signature = catalogSignature(
				config,
				catalog.map((model) => model.id),
				models.map((model) => model.id),
			);
			if (signature === lastCatalogSignature) return;
			pi.registerProvider(PROVIDER, { models });
			lastCatalogSignature = signature;
		} catch {
			// Never break a turn.
		}
	}

	async function syncKey(ctx: unknown): Promise<string | undefined> {
		const runtime = getRuntime(ctx);
		if (!runtime) {
			return (
				"⚠ pi internals changed: ctx.modelRegistry.runtime.setRuntimeApiKey/removeRuntimeApiKey " +
				"not found. openrouter-gate needs updating for this pi version."
			);
		}
		const stash = readStash();
		const wantKey = isProviderOpen(config) && Boolean(stash.key);
		if (wantKey && stash.key) {
			if (!keyInjected) {
				try {
					await runtime.setRuntimeApiKey(PROVIDER, stash.key, { allowNetwork: true });
				} catch (e) {
					return `⚠ setRuntimeApiKey failed: ${e instanceof Error ? e.message : String(e)}`;
				}
				process.env[ENV_VAR] = stash.key;
				keyInjected = true;
			}
			return undefined;
		}
		if (keyInjected) {
			try {
				await runtime.removeRuntimeApiKey(PROVIDER);
			} catch (e) {
				return `⚠ removeRuntimeApiKey failed: ${e instanceof Error ? e.message : String(e)}`;
			}
			delete process.env[ENV_VAR];
			keyInjected = false;
		}
		return undefined;
	}

	function persist(next: OpenRouterGateConfig): void {
		config = next;
		lastCatalogSignature = "";
		saveConfig(configPath, config);
	}

	async function pickModel(
		ctx: { hasUI?: boolean; ui?: { custom?: Function } },
		title: string,
		models: readonly PickerModel[],
	): Promise<string | undefined> {
		if (!ctx.hasUI || typeof ctx.ui?.custom !== "function" || models.length === 0) return undefined;
		const { createModelPicker } = await import("./picker.ts");
		const result = await ctx.ui.custom(
			(tui: any, theme: any, keybindings: any, done: (value: string | null) => void) =>
				createModelPicker(tui, theme, keybindings, done, models, title),
			{
				overlay: true,
				overlayOptions: {
					width: "80%",
					maxHeight: "70%",
					row: "14%",
					col: "50%",
					minWidth: 60,
				},
			},
		);
		return result || undefined;
	}

	async function ensurePickerCatalog(ctx: unknown): Promise<PickerModel[]> {
		rememberPickerModels(getOpenRouterModels(ctx));
		try {
			await fetchOpenRouterModels();
		} catch {
			// Fall back to whatever we've already seen in the registry.
		}
		return getCachedPickerModels();
	}

	async function applyGate(ctx: unknown): Promise<string | undefined> {
		const keyError = await syncKey(ctx);
		applyCatalog(ctx);
		return keyError;
	}

	pi.on("session_start", async (_event: unknown, ctx: any) => {
		try {
			config = loadConfig(configPath);
			lastCatalogSignature = "";
			if (ctx?.hasUI && readStash().liveEntryPresent) ctx.ui.notify(LIVE_ENTRY_WARNING, "warning");
			await syncKey(ctx);
			applyCatalog(ctx);
			void fetchOpenRouterModels().catch(() => {
				// Completions still work from the registry snapshot.
			});
		} catch {
			// Never break a turn.
		}
	});

	pi.on("resources_discover", async (_event: unknown, ctx: any) => {
		try {
			applyCatalog(ctx);
		} catch {
			// Never break a turn.
		}
	});

	pi.on("before_agent_start", async (_event: unknown, ctx: any) => {
		try {
			applyCatalog(ctx);
		} catch {
			// Never break a turn.
		}
	});

	pi.on("model_select", async (_event: unknown, ctx: any) => {
		try {
			applyCatalog(ctx);
		} catch {
			// Never break a turn.
		}
	});

	pi.registerCommand("openrouter", {
		description: "OpenRouter gate: /openrouter on | off | status | reload | allow | deny",
		getArgumentCompletions: (prefix: string) =>
			commandCompletions(prefix, getCachedPickerModels(), config.allowedModels),
		handler: async (args: string, ctx: any) => {
			const cmd = parseCommand(args);
			const stash = readStash();
			const usage = "Usage: /openrouter on | off | status | reload | allow [id|glob] | deny [id]";

			if (cmd.kind === "help") {
				return usage;
			}

			if (cmd.kind === "status") {
				config = loadConfig(configPath);
				const catalogCount = getOpenRouterModels(ctx).length;
				const lines = [
					describeConfig(config),
					keyInjected
						? `runtime key: injected (subagents inherit ${ENV_VAR})`
						: "runtime key: not injected",
					stash.stashPresent
						? `stash: "${STASH_ID}" present in auth.json${stash.key ? "" : " but has no usable key"}`
						: `stash: MISSING — ${MISSING_STASH_WARNING}`,
					`config: ${configPath}`,
					isProviderOpen(config)
						? `catalog: ${catalogCount} OpenRouter model(s) currently registered`
						: "catalog: hidden (provider closed or allowlist empty)",
				];
				if (stash.liveEntryPresent) lines.push(LIVE_ENTRY_WARNING);
				if (stash.error) lines.push(`auth.json read error: ${stash.error}`);
				if (config.enabled && config.allowedModels.length === 0) lines.push(EMPTY_ALLOWLIST_WARNING);
				return lines.join("\n");
			}

			if (cmd.kind === "reload") {
				config = loadConfig(configPath);
				lastCatalogSignature = "";
				const keyError = await applyGate(ctx);
				if (keyError) return `${describeConfig(config)}\n${keyError}`;
				return `${describeConfig(config)}; reloaded from ${configPath}`;
			}

			if (cmd.kind === "allow") {
				let id = cmd.id;
				if (!id) {
					const catalog = await ensurePickerCatalog(ctx);
					const choices = pickerItemsExcluding(catalog, config.allowedModels);
					id = await pickModel(ctx, "Allow OpenRouter model", choices);
					if (!id && ctx.hasUI && typeof ctx.ui?.input === "function" && choices.length === 0) {
						id = (await ctx.ui.input("OpenRouter model id or glob", "z-ai/glm-5.3-flash"))?.trim();
					}
				}
				if (!id) {
					return ctx.hasUI ? undefined : `${usage}\nPass a model id, or run this in the TUI to pick one.`;
				}
				const result = addAllowedModel(config.allowedModels, id);
				if (!result.added) return `${id} is already on the allowlist.\n${describeConfig(config)}`;
				persist({ ...config, allowedModels: result.allowed });
				const keyError = await applyGate(ctx);
				const extra = keyError ? `\n${keyError}` : "";
				return `+ allowed ${id}. ${describeConfig(config)}${extra}`;
			}

			if (cmd.kind === "deny") {
				let id = cmd.id;
				if (!id) {
					if (config.allowedModels.length === 0) {
						return `Allowlist already empty.\n${describeConfig(config)}`;
					}
					id = await pickModel(
						ctx,
						"Remove from OpenRouter allowlist",
						config.allowedModels.map((entry) => ({ id: entry, name: entry })),
					);
				}
				if (!id) {
					return ctx.hasUI ? undefined : `${usage}\nPass an allowlist entry, or run this in the TUI to pick one.`;
				}
				const result = removeAllowedModel(config.allowedModels, id);
				if (!result.removed) return `${id} is not on the allowlist.\n${describeConfig(config)}`;
				persist({ ...config, allowedModels: result.allowed });
				const keyError = await applyGate(ctx);
				const extra = [
					config.enabled && config.allowedModels.length === 0 ? EMPTY_ALLOWLIST_WARNING : "",
					keyError ?? "",
				].filter(Boolean);
				return `- removed ${id}. ${describeConfig(config)}${extra.length ? `\n${extra.join("\n")}` : ""}`;
			}

			const runtimeErrorProbe = getRuntime(ctx);
			if (!runtimeErrorProbe) {
				return (
					"⚠ pi internals changed: ctx.modelRegistry.runtime.setRuntimeApiKey/removeRuntimeApiKey " +
					"not found. openrouter-gate needs updating for this pi version."
				);
			}

			if (cmd.kind === "on") {
				persist({ ...config, enabled: true });
				if (config.allowedModels.length === 0) {
					await applyGate(ctx);
					ctx.ui?.notify?.(EMPTY_ALLOWLIST_WARNING, "warning");
					return `${describeConfig(config)}\n${EMPTY_ALLOWLIST_WARNING}`;
				}
				if (!stash.key) {
					await applyGate(ctx);
					ctx.ui?.notify?.(MISSING_STASH_WARNING, "warning");
					return MISSING_STASH_WARNING;
				}
				const keyError = await applyGate(ctx);
				if (keyError) return keyError;
				const extra = stash.liveEntryPresent ? `\n${LIVE_ENTRY_WARNING}` : "";
				return (
					`◉ OpenRouter enabled (persisted). ${describeConfig(config)}. ` +
					`Subagents spawned from here inherit ${ENV_VAR}.` +
					extra
				);
			}

			if (!config.enabled && !keyInjected && !stash.liveEntryPresent) {
				return `${describeConfig(config)}\nOpenRouter already disabled.`;
			}
			persist({ ...config, enabled: false });
			const keyError = await applyGate(ctx);
			if (keyError) return keyError;
			return stash.liveEntryPresent
				? `○ OpenRouter disabled (persisted). Catalog hidden — but ${LIVE_ENTRY_WARNING}`
				: `○ OpenRouter disabled (persisted). ${describeConfig(config)}`;
		},
	});
}
