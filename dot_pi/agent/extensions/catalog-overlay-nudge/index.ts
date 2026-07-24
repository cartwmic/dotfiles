/**
 * catalog-overlay-nudge — pi extension
 *
 * Detects when a temporary model overlay in ~/.pi/agent/models.json has been
 * superseded by the real catalog, and nudges at session start to remove it.
 *
 * Why: brand-new models (e.g. claude-opus-5 on release day) are absent from
 * both pi's bundled pi-ai catalog and the pi.dev remote catalog, so we bridge
 * the gap with a models.json overlay carrying guessed metadata (placeholder
 * cost etc.). Once the catalog catches up, the overlay *shadows* the official
 * entry — modelFromJson replaces the catalog model wholesale — so stale
 * overlays silently pin wrong pricing/compat. This extension compares each
 * overlay model id against the union of:
 *
 *   1. pi-ai's builtin catalog (getModels(provider), bundled with pi), and
 *   2. the persisted pi.dev remote-catalog overlay (~/.pi/agent/models-store.json,
 *      refreshed every 4h by pi itself)
 *
 * and warns when an overlay id now exists upstream.
 *
 * Scope guard: only provider entries whose ONLY key is "models" are considered
 * catalog stopgaps. Entries that also configure baseUrl/apiKey/compat/etc.
 * (deepseek, private-anthropic) are permanent custom providers and are skipped.
 */

import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { getModels } from "@mariozechner/pi-ai";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

const AGENT_DIR = path.join(os.homedir(), ".pi", "agent");
const MODELS_JSON = path.join(AGENT_DIR, "models.json");
const MODELS_STORE_JSON = path.join(AGENT_DIR, "models-store.json");
// Chezmoi source of models.json — mentioned in the nudge so the fix lands in
// the right place instead of being clobbered by the next `chezmoi apply`.
const CHEZMOI_SOURCE = "dot_pi/agent/private_models.json.tmpl";

function readJson(file: string): any | null {
	try {
		return JSON.parse(fs.readFileSync(file, "utf8"));
	} catch {
		return null;
	}
}

/** Overlay entries that exist purely to inject models into a builtin provider. */
function isCatalogStopgap(providerConfig: unknown): providerConfig is { models: Array<{ id?: string }> } {
	return (
		typeof providerConfig === "object" &&
		providerConfig !== null &&
		Array.isArray((providerConfig as any).models) &&
		Object.keys(providerConfig).length === 1
	);
}

/** Ids the catalog already knows for a provider: builtin pi-ai ∪ pi.dev store. */
function knownCatalogIds(providerId: string, store: any): Set<string> {
	const known = new Set<string>();
	try {
		for (const m of ((getModels as any)(providerId) ?? []) as Array<{ id?: string }>) {
			if (m?.id) known.add(m.id);
		}
	} catch {
		// builtin catalog lookup is best-effort
	}
	const storeModels = store?.[providerId]?.models;
	if (Array.isArray(storeModels)) {
		for (const m of storeModels as Array<{ id?: string }>) {
			if (m?.id) known.add(m.id);
		}
	}
	return known;
}

export function findStaleOverlays(
	modelsJson: any,
	store: any,
): Array<{ provider: string; ids: string[] }> {
	const providers = modelsJson?.providers;
	if (typeof providers !== "object" || providers === null) return [];
	const stale: Array<{ provider: string; ids: string[] }> = [];
	for (const [providerId, config] of Object.entries(providers)) {
		if (!isCatalogStopgap(config)) continue;
		const known = knownCatalogIds(providerId, store);
		if (known.size === 0) continue; // fully custom provider — nothing upstream to defer to
		const ids = config.models
			.map((m) => m?.id)
			.filter((id): id is string => typeof id === "string" && known.has(id));
		if (ids.length > 0) stale.push({ provider: providerId, ids });
	}
	return stale;
}

export default function (pi: ExtensionAPI) {
	pi.on("session_start", async (_event: unknown, ctx: any) => {
		const stale = findStaleOverlays(readJson(MODELS_JSON), readJson(MODELS_STORE_JSON));
		if (stale.length === 0 || !ctx.hasUI) return;
		const detail = stale
			.map(({ provider, ids }) => `${provider}: ${ids.join(", ")}`)
			.join("; ");
		ctx.ui.notify(
			`Model catalog now includes overlay-defined model(s) — ${detail}. ` +
				`Remove the stopgap overlay from ${CHEZMOI_SOURCE} (chezmoi) so official metadata/pricing applies.`,
			"warning",
		);
	});
}
