/**
 * TUI model picker for `/issue config model`, matching the pi builtin picker
 * feel (type-to-filter, substring match over provider/id).
 *
 * This module statically imports @mariozechner/pi-tui, which pi resolves at
 * runtime but is NOT installed on disk for `bun test`. It is therefore loaded
 * via dynamic `import()` from index.ts (only when the command runs) so the
 * offline unit tests never resolve pi-tui.
 */
import type { ExtensionCommandContext } from "@mariozechner/pi-coding-agent";
import { Input, SelectList, type Component, type Focusable, type SelectItem, type Theme } from "@mariozechner/pi-tui";
import { filterCatalog } from "./summary.ts";

/**
 * SelectList with contains/substring filter (stock setFilter is startsWith-only).
 *
 * NOTE: reaches into SelectList private fields (`items`, `filteredItems`,
 * `selectedIndex`) which are NOT part of the public contract. Verified against
 * @earendil-works/pi-coding-agent 0.81.1. If a pi-tui refactor renames these,
 * the guard below falls back to the stock (startsWith) filter instead of
 * silently showing wrong/blank results.
 */
class ContainsSelectList extends SelectList {
	override setFilter(filter: string): void {
		const self = this as unknown as {
			items?: SelectItem[];
			filteredItems?: SelectItem[];
			selectedIndex?: number;
		};
		// Verify ALL three private fields exist in the expected shape before reaching
		// in; if any moved, fall back to stock filtering instead of writing phantom
		// properties (which would silently show the full/blank catalog).
		if (
			!Array.isArray(self.items) ||
			!Array.isArray(self.filteredItems) ||
			typeof self.selectedIndex !== "number"
		) {
			super.setFilter(filter);
			return;
		}
		self.filteredItems = self.items.filter((item) => filterCatalog([item.value], filter).length > 0);
		self.selectedIndex = 0;
		this.invalidate();
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

	constructor(
		private theme: Theme,
		private done: (result: string | undefined) => void,
		catalog: string[],
		private prompt: string,
	) {
		const items = catalog.map((id) => ({ value: id, label: id }));
		this.list = new ContainsSelectList(items, Math.min(items.length, 12), selectListTheme(theme));
		this.list.onSelect = (item) => this.done(item.value);
		this.list.onCancel = () => this.done(undefined);
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
		this.list.handleInput(data);
	}
}

/** Show the filterable picker over `catalog`. Resolves to a `provider/id` or undefined. */
export async function pickModel(
	ctx: ExtensionCommandContext,
	catalog: string[],
	prompt = "summary model (type to filter, esc to cancel)",
): Promise<string | undefined> {
	if (typeof ctx.ui?.custom !== "function") return undefined;
	return ctx.ui.custom<string | undefined>(
		(_tui, theme, _kb, done) => new ModelPickerComponent(theme, done, catalog, prompt),
		{ overlay: true, overlayOptions: { anchor: "center", width: 72, maxHeight: "70%" } },
	);
}
