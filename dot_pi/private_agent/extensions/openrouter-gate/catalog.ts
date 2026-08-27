import { modelAllowed, OPENROUTER_BASE_URL } from "./config.ts";

export const OPENROUTER_MODELS_URL = `${OPENROUTER_BASE_URL}/models`;
const CACHE_TTL_MS = 30 * 60 * 1000;
const FETCH_TIMEOUT_MS = 15_000;

export interface PickerModel {
	id: string;
	name: string;
}

export const SUBCOMMANDS = ["on", "off", "status", "reload", "allow", "deny", "stash", "help"] as const;

export type GateCommand =
	| { kind: "on" | "off" | "status" | "reload" | "help" }
	| { kind: "allow" | "deny"; id?: string }
	| { kind: "stash"; key?: string };

let cachedModels: PickerModel[] = [];
let cacheTimestamp = 0;

export function isCanonicalOpenRouterId(id: string): boolean {
	if (!id || id.startsWith("@or:")) return false;
	return id.includes("/");
}

export function normalizeAllowId(id: string): string {
	const trimmed = id.trim();
	if (trimmed.startsWith("openrouter/")) return trimmed.slice("openrouter/".length);
	return trimmed;
}

export function parseCommand(args: string): GateCommand {
	const trimmed = (args ?? "").trim();
	if (!trimmed || /^status$/i.test(trimmed)) return { kind: "status" };
	const match = /^(on|off|reload|help|allow|deny|stash)(?:\s+([\s\S]+))?$/i.exec(trimmed);
	if (!match) return { kind: "help" };
	const kind = match[1]!.toLowerCase();
	if (kind === "allow" || kind === "deny") {
		const id = match[2]?.trim();
		return { kind, id: id ? normalizeAllowId(id) : undefined };
	}
	if (kind === "stash") {
		const key = match[2]?.trim();
		return { kind: "stash", key: key || undefined };
	}
	return { kind: kind as "on" | "off" | "reload" | "help" };
}

export function parseModelsResponse(json: unknown): PickerModel[] {
	const data =
		json && typeof json === "object" && Array.isArray((json as { data?: unknown }).data)
			? ((json as { data: unknown[] }).data)
			: [];
	const out: PickerModel[] = [];
	const seen = new Set<string>();
	for (const item of data) {
		if (!item || typeof item !== "object") continue;
		const raw = item as { id?: unknown; name?: unknown };
		const id = typeof raw.id === "string" ? raw.id.trim() : "";
		if (!isCanonicalOpenRouterId(id) || seen.has(id)) continue;
		seen.add(id);
		const name = typeof raw.name === "string" && raw.name.trim() ? raw.name.trim() : id;
		out.push({ id, name });
	}
	return out;
}

export function mergePickerModels(...lists: readonly (readonly PickerModel[])[]): PickerModel[] {
	const map = new Map<string, PickerModel>();
	for (const list of lists) {
		for (const model of list) {
			if (!isCanonicalOpenRouterId(model.id)) continue;
			if (!map.has(model.id)) map.set(model.id, { id: model.id, name: model.name || model.id });
		}
	}
	return [...map.values()].sort((a, b) => a.id.localeCompare(b.id));
}

export function pickerSearchText(model: PickerModel): string {
	return `${model.id} ${model.id.replace(/[/_:.-]+/g, " ")} ${model.name}`;
}

/** Subsequence match; lower score is better. Tokens split on whitespace and slashes. */
export function fuzzyMatch(query: string, text: string): { matches: boolean; score: number } {
	const q = query.toLowerCase();
	const t = text.toLowerCase();
	if (!q) return { matches: true, score: 0 };
	let ti = 0;
	let score = 0;
	let last = -2;
	for (const ch of q) {
		const found = t.indexOf(ch, ti);
		if (found < 0) return { matches: false, score: Number.POSITIVE_INFINITY };
		score += found === last + 1 ? 0 : 1;
		last = found;
		ti = found + 1;
	}
	return { matches: true, score };
}

export function fuzzyFilter<T>(items: readonly T[], query: string, getText: (item: T) => string): T[] {
	const tokens = query
		.trim()
		.toLowerCase()
		.split(/[\s/]+/)
		.filter(Boolean);
	if (tokens.length === 0) return [...items];
	return items
		.map((item) => {
			const text = getText(item);
			let score = 0;
			for (const token of tokens) {
				const match = fuzzyMatch(token, text);
				if (!match.matches) return null;
				score += match.score;
			}
			return { item, score };
		})
		.filter((entry): entry is { item: T; score: number } => entry !== null)
		.sort((a, b) => a.score - b.score || getText(a.item).localeCompare(getText(b.item)))
		.map((entry) => entry.item);
}

export function rankPickerModels(models: readonly PickerModel[], query: string): PickerModel[] {
	const trimmed = query.trim();
	if (!trimmed) return [...models].sort((a, b) => a.id.localeCompare(b.id));
	return fuzzyFilter(models, trimmed, pickerSearchText);
}

export function pickerItemsExcluding(
	models: readonly PickerModel[],
	allowed: readonly string[],
): PickerModel[] {
	return models.filter((model) => !modelAllowed(model.id, allowed));
}

export function addAllowedModel(
	allowed: readonly string[],
	id: string,
): { allowed: string[]; added: boolean } {
	const normalized = normalizeAllowId(id);
	if (!normalized || allowed.includes(normalized)) return { allowed: [...allowed], added: false };
	return { allowed: [...allowed, normalized], added: true };
}

export function removeAllowedModel(
	allowed: readonly string[],
	id: string,
): { allowed: string[]; removed: boolean } {
	const normalized = normalizeAllowId(id);
	if (!allowed.includes(normalized)) return { allowed: [...allowed], removed: false };
	return { allowed: allowed.filter((item) => item !== normalized), removed: true };
}

export function commandCompletions(
	prefix: string,
	catalog: readonly PickerModel[],
	allowed: readonly string[],
): { value: string; label: string; description?: string }[] {
	if (!prefix.includes(" ")) {
		const p = prefix.trim().toLowerCase();
		return SUBCOMMANDS.filter((sub) => sub.startsWith(p)).map((sub) => ({
			value: sub === "allow" || sub === "deny" ? `${sub} ` : sub,
			label: sub,
		}));
	}
	const parsed = parseCommand(prefix);
	if (parsed.kind === "allow") {
		const query = parsed.id ?? "";
		const ranked = rankPickerModels(pickerItemsExcluding(catalog, allowed), query).slice(0, 20);
		const items = ranked.map((model) => ({
			value: `allow ${model.id}`,
			label: model.id,
			description: model.name !== model.id ? model.name : undefined,
		}));
		if (query && !ranked.some((model) => model.id === query)) {
			items.unshift({
				value: `allow ${query}`,
				label: query,
				description: /[*?]/.test(query) ? "glob pattern" : "exact id",
			});
		}
		return items;
	}
	if (parsed.kind === "deny") {
		const query = parsed.id ?? "";
		const ranked = rankPickerModels(
			allowed.map((id) => ({ id, name: id })),
			query,
		).slice(0, 20);
		return ranked.map((model) => ({ value: `deny ${model.id}`, label: model.id }));
	}
	return [];
}

export function resetPickerCache(): void {
	cachedModels = [];
	cacheTimestamp = 0;
}

export function getCachedPickerModels(): PickerModel[] {
	return cachedModels;
}

export function rememberPickerModels(models: readonly { id: string; name?: string }[]): void {
	cachedModels = mergePickerModels(
		cachedModels,
		models.map((model) => ({ id: model.id, name: model.name || model.id })),
	);
}

export async function fetchOpenRouterModels(
	deps: { fetch?: typeof fetch; now?: () => number } = {},
): Promise<PickerModel[]> {
	const now = deps.now ?? Date.now;
	if (cachedModels.length > 0 && cacheTimestamp > 0 && now() - cacheTimestamp < CACHE_TTL_MS) {
		return cachedModels;
	}
	const fetchFn = deps.fetch ?? fetch;
	const response = await fetchFn(OPENROUTER_MODELS_URL, {
		signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
		headers: { Accept: "application/json" },
	});
	if (!response.ok) {
		throw new Error(`OpenRouter models ${response.status} ${response.statusText}`);
	}
	const parsed = parseModelsResponse(await response.json());
	cachedModels = mergePickerModels(cachedModels, parsed);
	cacheTimestamp = now();
	return cachedModels;
}
