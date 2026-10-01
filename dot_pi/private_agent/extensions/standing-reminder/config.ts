import { readFileSync } from "node:fs";

export const DEFAULT_TRIGGERS = ["tool-result:ask_user_question"];
export function readTriggerConfig(path: string): { triggers: Set<string>; warning?: string } {
	try {
		const value = JSON.parse(readFileSync(path, "utf8"));
		if (!value || !Array.isArray(value.triggers) || !value.triggers.every((entry: unknown) =>
			typeof entry === "string" && /^(tool-result|message):[^\s:*]+$/.test(entry))) throw new Error("invalid selectors");
		return { triggers: new Set(value.triggers) };
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code === "ENOENT") return { triggers: new Set(DEFAULT_TRIGGERS) };
		return { triggers: new Set(), warning: "Invalid standing-reminder config; event refreshes disabled until reload." };
	}
}
