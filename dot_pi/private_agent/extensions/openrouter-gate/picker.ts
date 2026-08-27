import {
	Input,
	Key,
	matchesKey,
	truncateToWidth,
	type Component,
	type Focusable,
} from "@earendil-works/pi-tui";
import { type PickerModel, rankPickerModels } from "./catalog.ts";

const VIEWPORT_ROWS = 12;

export function createModelPicker(
	tui: { requestRender: (force?: boolean) => void },
	theme: { fg: (color: string, text: string) => string },
	_keybindings: unknown,
	done: (result: string | null) => void,
	models: readonly PickerModel[],
	title: string,
): Component & Focusable {
	const searchInput = new Input();
	searchInput.focused = true;
	let filtered = rankPickerModels(models, "");
	let selectedIndex = 0;

	function refilter(): void {
		filtered = rankPickerModels(models, searchInput.getValue());
		selectedIndex = filtered.length === 0 ? 0 : Math.min(selectedIndex, filtered.length - 1);
	}

	function move(delta: number): void {
		if (filtered.length === 0) return;
		selectedIndex = (selectedIndex + delta + filtered.length) % filtered.length;
	}

	return {
		get focused() {
			return searchInput.focused;
		},
		set focused(value: boolean) {
			searchInput.focused = value;
		},
		invalidate() {
			searchInput.invalidate();
		},
		handleInput(data: string) {
			if (matchesKey(data, Key.escape) || matchesKey(data, Key.esc) || matchesKey(data, Key.ctrl("c"))) {
				done(null);
				return;
			}
			if (matchesKey(data, Key.enter) || matchesKey(data, Key.return)) {
				done(filtered[selectedIndex]?.id ?? null);
				return;
			}
			if (matchesKey(data, Key.up) || matchesKey(data, Key.ctrl("p"))) {
				move(-1);
				tui.requestRender?.(true);
				return;
			}
			if (matchesKey(data, Key.down) || matchesKey(data, Key.ctrl("n"))) {
				move(1);
				tui.requestRender?.(true);
				return;
			}
			if (matchesKey(data, Key.pageUp)) {
				move(-VIEWPORT_ROWS);
				tui.requestRender?.(true);
				return;
			}
			if (matchesKey(data, Key.pageDown)) {
				move(VIEWPORT_ROWS);
				tui.requestRender?.(true);
				return;
			}
			searchInput.handleInput(data);
			refilter();
			tui.requestRender?.(true);
		},
		render(width: number) {
			const lines: string[] = [];
			lines.push(truncateToWidth(theme.fg("accent", title), width));
			lines.push(truncateToWidth(theme.fg("dim", "Type to filter • ↑↓ navigate • enter select • esc cancel"), width));
			for (const line of searchInput.render(width)) {
				lines.push(truncateToWidth(`${theme.fg("muted", "Search: ")}${line}`, width));
			}
			const start = Math.max(
				0,
				Math.min(selectedIndex - Math.floor(VIEWPORT_ROWS / 2), Math.max(0, filtered.length - VIEWPORT_ROWS)),
			);
			const end = Math.min(filtered.length, start + VIEWPORT_ROWS);
			if (filtered.length === 0) {
				lines.push(truncateToWidth(theme.fg("muted", "  No matching models"), width));
			} else {
				for (let i = start; i < end; i++) {
					const model = filtered[i]!;
					const selected = i === selectedIndex;
					const prefix = selected ? theme.fg("accent", "→ ") : "  ";
					const id = selected ? theme.fg("accent", model.id) : model.id;
					const suffix =
						model.name && model.name !== model.id ? ` ${theme.fg("muted", `— ${model.name}`)}` : "";
					lines.push(truncateToWidth(`${prefix}${id}${suffix}`, width));
				}
			}
			const shown = filtered.length === 0 ? "0 of 0" : `${start + 1}-${end} of ${filtered.length}`;
			lines.push(truncateToWidth(theme.fg("dim", `Showing ${shown}`), width));
			return lines;
		},
	};
}
