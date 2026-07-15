/**
 * pi TUI layer for interactive `/opsx-loop models set` (Path B).
 * (opsx-loop.model-config-subcommand)
 */
import type { ExtensionContext } from "@mariozechner/pi-coding-agent";
import { Input, SelectList, type Component, type Focusable, type SelectItem, type Theme } from "@mariozechner/pi-tui";
import {
	appendThinkingSuffix,
	fetchModelsCatalogDefault,
	MODEL_ROLES,
	THINK_LEVELS,
	type CatalogFetchResult,
	type InteractiveSetPlan,
	type ModelRole,
	planInteractiveSetCliArgs,
	isModelRole,
} from "./model-config.ts";

/** SelectList with contains/substring filter (stock setFilter is startsWith-only). */
export class ContainsSelectList extends SelectList {
	override setFilter(filter: string): void {
		const f = filter.toLowerCase();
		(this as { filteredItems: SelectItem[] }).filteredItems = (this as { items: SelectItem[] }).items.filter(
			(item) => item.value.toLowerCase().includes(f),
		);
		(this as { selectedIndex: number }).selectedIndex = 0;
	}
}

function selectListTheme(theme: Theme) {
	return {
		selectedPrefix: (t: string) => theme.fg("accent", t),
		selectedText: (t: string) => theme.fg("accent", t),
		description: (t: string) => theme.fg("muted", t),
		scrollInfo: (t: string) => theme.fg("dim", t),
		noMatch: (t: string) => theme.fg("warning", t),
	};
}

class ModelPickerComponent implements Component, Focusable {
	focused = true;
	private input: Input;
	private list: ContainsSelectList;
	private prompt: string;
	private allowEmptyDone: boolean;

	constructor(
		private theme: Theme,
		private done: (result: string | undefined) => void,
		catalog: string[],
		prompt: string,
		allowEmptyDone: boolean,
	) {
		this.prompt = prompt;
		this.allowEmptyDone = allowEmptyDone;
		const items = catalog.map((id) => ({ value: id, label: id }));
		this.list = new ContainsSelectList(items, Math.min(items.length, 12), selectListTheme(theme));
		this.list.onSelect = (item) => {
			this.done(item.value);
		};
		this.list.onCancel = () => {
			this.done(undefined);
		};
		this.input = new Input();
		this.input.focused = true;
	}

	invalidate(): void {
		this.input.invalidate();
		this.list.invalidate();
	}

	render(width: number): string[] {
		const lines: string[] = [];
		lines.push(this.theme.fg("muted", this.prompt));
		lines.push(this.theme.fg("dim", "filter:") + " " + (this.input.getValue() || "(type to filter)"));
		lines.push(...this.list.render(width));
		if (this.allowEmptyDone) {
			lines.push(this.theme.fg("dim", "  Enter on empty filter when done (review)"));
		}
		return lines;
	}

	handleInput(data: string): void {
		const before = this.input.getValue();
		this.input.handleInput(data);
		const after = this.input.getValue();
		if (before !== after) {
			this.list.setFilter(after);
			return;
		}
		if (this.allowEmptyDone && (data === "\r" || data === "\n") && !after.trim()) {
			this.done(undefined);
			return;
		}
		this.list.handleInput(data);
	}
}

async function pickModelFromCatalog(
	ctx: ExtensionContext,
	catalog: string[],
	prompt: string,
	allowEmptyDone: boolean,
): Promise<string | undefined> {
	if (!ctx.ui?.custom) return undefined;
	return ctx.ui.custom<string | undefined>(
		(_tui, theme, _kb, done) =>
			new ModelPickerComponent(theme, done, catalog, prompt, allowEmptyDone),
		{ overlay: true, overlayOptions: { anchor: "center", width: 72, maxHeight: "70%" } },
	);
}

async function pickRole(ctx: ExtensionContext): Promise<ModelRole | undefined> {
	if (typeof ctx.ui?.select !== "function") return undefined;
	const pick = (await ctx.ui.select("Role?", [...MODEL_ROLES])) as string | undefined;
	return pick && isModelRole(pick) ? pick : undefined;
}

async function pickThinkingLevel(ctx: ExtensionContext): Promise<string | undefined> {
	if (typeof ctx.ui?.select !== "function") return undefined;
	const options = [...THINK_LEVELS, "skip"];
	return (await ctx.ui.select("Thinking level?", options)) as string | undefined;
}

async function pickAuthorInSession(ctx: ExtensionContext): Promise<boolean | undefined> {
	if (typeof ctx.ui?.select !== "function") return undefined;
	const pick = (await ctx.ui.select("author-in-session?", ["true", "false"])) as string | undefined;
	if (pick === "true") return true;
	if (pick === "false") return false;
	return undefined;
}

/**
 * In-TUI interactive models set: role → pick(s) → thinking → `opsx models set` argv.
 * Never writes YAML from the extension.
 */
export async function runInteractiveModelsSet(
	ctx: ExtensionContext,
	preselectedRole?: string,
	deps?: {
		fetchCatalog?: () => CatalogFetchResult;
	},
): Promise<InteractiveSetPlan> {
	const fetchCatalog = deps?.fetchCatalog ?? fetchModelsCatalogDefault;

	let role: ModelRole | undefined =
		preselectedRole && isModelRole(preselectedRole) ? preselectedRole : undefined;
	if (!role) {
		role = await pickRole(ctx);
		if (!role) return { ok: false, error: "role selection cancelled" };
	}

	if (role === "author-in-session") {
		const ais = await pickAuthorInSession(ctx);
		return planInteractiveSetCliArgs({ role, authorInSession: ais });
	}

	const catalogResult = fetchCatalog();
	if (!catalogResult.ok) return catalogResult;

	if (role === "review") {
		const picked: string[] = [];
		let remaining = catalogResult.catalog.slice();
		while (remaining.length > 0) {
			const model = await pickModelFromCatalog(
				ctx,
				remaining,
				"review model (esc/empty when done)",
				true,
			);
			if (!model) break;
			const level = await pickThinkingLevel(ctx);
			if (level === undefined) return { ok: false, error: "thinking selection cancelled" };
			picked.push(appendThinkingSuffix(model, level));
			remaining = remaining.filter((id) => id !== model);
		}
		return planInteractiveSetCliArgs({ role: "review", reviewModels: picked });
	}

	const model = await pickModelFromCatalog(ctx, catalogResult.catalog, "model", false);
	if (!model) return { ok: false, error: "selection cancelled" };
	const level = await pickThinkingLevel(ctx);
	if (level === undefined) return { ok: false, error: "thinking selection cancelled" };
	return planInteractiveSetCliArgs({
		role,
		scalarModel: appendThinkingSuffix(model, level),
	});
}
