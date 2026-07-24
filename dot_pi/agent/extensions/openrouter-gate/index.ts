/**
 * openrouter-gate — pi extension: OpenRouter provider default-OFF, with an
 * in-session opt-in toggle.
 *
 * Mechanism: pi gates model availability strictly by auth resolution — a
 * provider is configured iff auth.json has a matching entry or the provider's
 * env API key is set. There is no per-provider disable switch, and extensions
 * cannot unregister builtin providers. So the gate works by *absence*: the
 * OpenRouter API key is stashed in auth.json under the non-provider id
 * "openrouter-stashed" (invisible to the registry), and this extension
 * re-injects it on demand as a session-scoped runtime credential:
 *
 *   /openrouter on     read stash → modelRegistry.runtime.setRuntimeApiKey()
 *                      (in-memory overlay, same primitive as pi's --api-key
 *                      flag; never persisted) + set OPENROUTER_API_KEY in
 *                      process.env so spawned subagent children inherit it.
 *   /openrouter off    removeRuntimeApiKey() + unset the env var.
 *   /openrouter status show gate state and stash health.
 *
 * Session exit discards the overlay and env — every new session (and every
 * subagent not spawned from an enabled session) starts locked.
 *
 * KNOWN WEAK POINT: if pi ever rewrites auth.json wholesale (login/logout
 * flows), the unknown "openrouter-stashed" key could be silently dropped.
 * `/openrouter on` and `/openrouter status` warn loudly when the stash is
 * missing. session_start also warns if a *live* "openrouter" entry reappears
 * in auth.json (gate bypassed — provider would be always-on again).
 *
 * Hindsight rerank/embedding is unaffected: its OpenRouter key lives
 * server-side on hindsight-api, not in pi's auth.json.
 */
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

const PROVIDER = "openrouter";
const STASH_ID = "openrouter-stashed";
const ENV_VAR = "OPENROUTER_API_KEY";

export function defaultAuthPath(): string {
	return path.join(os.homedir(), ".pi", "agent", "auth.json");
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

export type Subcommand = "on" | "off" | "status" | "help";

/** Parse the /openrouter argument string. Unknown/empty ⇒ status/help. */
export function parseSubcommand(args: string): Subcommand {
	const a = (args ?? "").trim().toLowerCase();
	if (a === "on") return "on";
	if (a === "off") return "off";
	if (a === "" || a === "status") return "status";
	return "help";
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

const MISSING_STASH_WARNING =
	`⚠ No "${STASH_ID}" entry in auth.json — cannot enable OpenRouter. ` +
	`If it was there before, pi may have rewritten auth.json (login/logout) and dropped the ` +
	`unknown key. Re-stash the API key as {"${STASH_ID}": {"type": "api_key", "key": "sk-or-..."}}.`;

const LIVE_ENTRY_WARNING =
	`⚠ A live "${PROVIDER}" entry exists in auth.json — the gate is bypassed and OpenRouter ` +
	`is always-on for every session and subagent. Rename it to "${STASH_ID}" to restore default-off.`;

export default function (pi: ExtensionAPI): void {
	let enabled = false;

	// Tripwire for the known weak point's inverse: a live entry reappearing
	// (e.g. after `pi /login openrouter`) silently defeats default-off.
	pi.on("session_start", async (_event: unknown, ctx: any) => {
		try {
			if (!ctx?.hasUI) return;
			if (readStash().liveEntryPresent) ctx.ui.notify(LIVE_ENTRY_WARNING, "warning");
		} catch {
			// Never break a turn.
		}
	});

	pi.registerCommand("openrouter", {
		description: "OpenRouter gate: /openrouter on | off | status (default-off, session-scoped)",
		getArgumentCompletions: (prefix: string) => {
			const p = prefix.trim().toLowerCase();
			return ["on", "off", "status"]
				.filter((s) => s.startsWith(p))
				.map((s) => ({ value: s, label: s }));
		},
		handler: async (args: string, ctx: any) => {
			const sub = parseSubcommand(args);
			const stash = readStash();

			if (sub === "help") {
				return "Usage: /openrouter on | off | status";
			}

			if (sub === "status") {
				const lines = [
					enabled
						? "◉ OpenRouter ENABLED for this session (runtime key + env propagation to subagents)."
						: "○ OpenRouter disabled (default). Enable with /openrouter on.",
					stash.stashPresent
						? `stash: "${STASH_ID}" present in auth.json${stash.key ? "" : " but has no usable key"}`
						: `stash: MISSING — ${MISSING_STASH_WARNING}`,
				];
				if (stash.liveEntryPresent) lines.push(LIVE_ENTRY_WARNING);
				if (stash.error) lines.push(`auth.json read error: ${stash.error}`);
				return lines.join("\n");
			}

			const runtime = getRuntime(ctx);
			if (!runtime) {
				return (
					"⚠ pi internals changed: ctx.modelRegistry.runtime.setRuntimeApiKey/removeRuntimeApiKey " +
					"not found. openrouter-gate needs updating for this pi version."
				);
			}

			if (sub === "on") {
				if (enabled) return "OpenRouter already enabled for this session.";
				if (!stash.key) {
					ctx.ui?.notify?.(MISSING_STASH_WARNING, "warning");
					return MISSING_STASH_WARNING;
				}
				try {
					await runtime.setRuntimeApiKey(PROVIDER, stash.key, { allowNetwork: true });
				} catch (e) {
					return `⚠ setRuntimeApiKey failed: ${e instanceof Error ? e.message : String(e)}`;
				}
				process.env[ENV_VAR] = stash.key;
				enabled = true;
				const extra = stash.liveEntryPresent ? `\n${LIVE_ENTRY_WARNING}` : "";
				return (
					"◉ OpenRouter enabled for THIS session only (models available now; subagents " +
					`spawned from here inherit ${ENV_VAR}). Auto-off at session end.` +
					extra
				);
			}

			// sub === "off"
			if (!enabled && !stash.liveEntryPresent) return "OpenRouter already disabled.";
			try {
				await runtime.removeRuntimeApiKey(PROVIDER);
			} catch (e) {
				return `⚠ removeRuntimeApiKey failed: ${e instanceof Error ? e.message : String(e)}`;
			}
			delete process.env[ENV_VAR];
			enabled = false;
			return stash.liveEntryPresent
				? `○ Runtime key removed — but ${LIVE_ENTRY_WARNING}`
				: "○ OpenRouter disabled.";
		},
	});
}
