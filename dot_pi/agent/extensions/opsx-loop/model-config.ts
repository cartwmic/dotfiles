/**
 * Pure helpers for interactive `/opsx-loop models set` (Path B).
 * Kept free of pi-tui imports so unit tests run hermetically.
 * (opsx-loop.model-config-subcommand)
 */
import { spawnSync } from "node:child_process";

export const MODEL_ROLES = ["author", "review", "impl", "author-in-session"] as const;
export type ModelRole = (typeof MODEL_ROLES)[number];

export const THINK_LEVELS = ["off", "minimal", "low", "medium", "high", "xhigh", "max"] as const;
export type ThinkLevel = (typeof THINK_LEVELS)[number] | "skip" | "none";

/** Longer than runModels' 10s default — catalog fetch can be slow. */
export const MODEL_CATALOG_TIMEOUT_MS = 60_000;

export type ModelsCommandRoute =
	| { kind: "list" }
	| { kind: "passthrough"; args: string[] }
	| { kind: "interactive-set"; role?: string };

export function isModelRole(s: string): s is ModelRole {
	return (MODEL_ROLES as readonly string[]).includes(s);
}

/**
 * Route `/opsx-loop models <args>`: bare → list; value-bearing set → passthrough;
 * bare/role-only set → interactive when UI available.
 */
export function classifyModelsCommand(args: string[]): ModelsCommandRoute {
	if (args.length === 0) return { kind: "list" };
	if (args[0] !== "set") return { kind: "passthrough", args };
	if (args.length === 1) return { kind: "interactive-set" };
	const role = args[1];
	if (args.length === 2 && isModelRole(role)) return { kind: "interactive-set", role };
	return { kind: "passthrough", args };
}

export function shouldRunInteractiveModelsSet(
	route: ModelsCommandRoute,
	hasUI: boolean,
	hasCustomUi: boolean,
): boolean {
	return route.kind === "interactive-set" && hasUI && hasCustomUi;
}

/** Parse columnar `pi --list-models` stdout → provider/id strings. */
export function parseListModelsOutput(stdout: string): string[] {
	const ids: string[] = [];
	for (const line of (stdout ?? "").split(/\r?\n/)) {
		const trimmed = line.trim();
		if (!trimmed) continue;
		const parts = trimmed.split(/\s+/);
		if (parts.length < 2) continue;
		if (parts[0]!.toLowerCase() === "provider") continue;
		ids.push(`${parts[0]}/${parts[1]}`);
	}
	return ids;
}

/** Substring/contains filter for catalog ids (case-insensitive). */
export function filterCatalogBySubstring(catalog: string[], filter: string): string[] {
	const f = filter.trim().toLowerCase();
	if (!f) return catalog.slice();
	return catalog.filter((id) => id.toLowerCase().includes(f));
}

export function appendThinkingSuffix(modelId: string, level: string | undefined): string {
	if (!level || level === "off" || level === "none" || level === "skip") return modelId;
	if (modelId.includes(":")) return modelId;
	return `${modelId}:${level}`;
}

export function buildModelsSetCliArgs(role: string, values: string[]): string[] {
	return ["set", role, ...values];
}

export type CatalogFetchResult =
	| { ok: true; catalog: string[] }
	| { ok: false; error: string };

type SpawnListModelsResult = {
	status: number | null;
	stdout: string;
	stderr: string;
	error?: Error;
};

export function fetchModelsCatalog(
	spawnFn: (cmd: string, args: string[], opts: { encoding: "utf-8"; timeout: number }) => SpawnListModelsResult,
	opts?: { piCmd?: string; timeoutMs?: number },
): CatalogFetchResult {
	const piCmd = opts?.piCmd ?? process.env.OPSX_MODELS_PI_CMD ?? "pi";
	const timeout = opts?.timeoutMs ?? MODEL_CATALOG_TIMEOUT_MS;
	try {
		const r = spawnFn(piCmd, ["--list-models"], { encoding: "utf-8", timeout });
		if (r.error) {
			return { ok: false, error: `failed to run: ${piCmd} --list-models: ${r.error.message}` };
		}
		if ((r.status ?? 1) !== 0) {
			const detail = `${r.stderr ?? ""}${r.stdout ?? ""}`.trim();
			return {
				ok: false,
				error: detail ? `pi --list-models failed: ${detail}` : `pi --list-models exited ${r.status ?? "non-zero"}`,
			};
		}
		const catalog = parseListModelsOutput(r.stdout ?? "");
		if (catalog.length === 0) {
			return { ok: false, error: "pi --list-models produced no parseable models" };
		}
		return { ok: true, catalog };
	} catch (e: unknown) {
		const msg = e instanceof Error ? e.message : String(e);
		return { ok: false, error: `failed to run: ${piCmd} --list-models: ${msg}` };
	}
}

export type InteractiveSetPlan =
	| { ok: true; cliArgs: string[] }
	| { ok: false; error: string };

/** Pure planner for the final `opsx models set` argv after interactive picks. */
export function planInteractiveSetCliArgs(input: {
	role: ModelRole;
	reviewModels?: string[];
	scalarModel?: string;
	authorInSession?: boolean;
}): InteractiveSetPlan {
	if (input.role === "author-in-session") {
		if (input.authorInSession === undefined) {
			return { ok: false, error: "author-in-session selection cancelled" };
		}
		return {
			ok: true,
			cliArgs: buildModelsSetCliArgs("author-in-session", [input.authorInSession ? "true" : "false"]),
		};
	}
	if (input.role === "review") {
		const models = input.reviewModels ?? [];
		if (models.length === 0) return { ok: false, error: "selection cancelled" };
		return { ok: true, cliArgs: buildModelsSetCliArgs("review", models) };
	}
	const scalar = input.scalarModel?.trim();
	if (!scalar) return { ok: false, error: "selection cancelled" };
	return { ok: true, cliArgs: buildModelsSetCliArgs(input.role, [scalar]) };
}

/** Default catalog fetch for interactive UI (60s timeout). */
export function fetchModelsCatalogDefault(): CatalogFetchResult {
	return fetchModelsCatalog(spawnSync as Parameters<typeof fetchModelsCatalog>[0]);
}
