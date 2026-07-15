/**
 * Unit tests for opsx-loop interactive model config (Path B).
 * AC: opsx-loop.model-config-subcommand
 */
import { describe, expect, test } from "bun:test";
import {
	appendThinkingSuffix,
	buildModelsSetCliArgs,
	classifyModelsCommand,
	fetchModelsCatalog,
	filterCatalogBySubstring,
	parseListModelsOutput,
	planInteractiveSetCliArgs,
	shouldRunInteractiveModelsSet,
} from "./model-config.ts";

const LIST_MODELS_FIXTURE = `provider      model                                                          context  max-out  thinking  images
anthropic     claude-sonnet-5                                                1M       128K     yes       yes
cursor        composer-2.5-fast                                              200K     16.4K    no        yes
anthropic     claude-opus-4-8                                                1M       128K     yes       yes
`;

describe("parseListModelsOutput — opsx-loop.model-config-subcommand", () => {
	test("parses columnar pi --list-models into provider/id", () => {
		expect(parseListModelsOutput(LIST_MODELS_FIXTURE)).toEqual([
			"anthropic/claude-sonnet-5",
			"cursor/composer-2.5-fast",
			"anthropic/claude-opus-4-8",
		]);
	});
	test("empty / header-only → no ids", () => {
		expect(parseListModelsOutput("provider model\n")).toEqual([]);
		expect(parseListModelsOutput("")).toEqual([]);
	});
});

describe("filterCatalogBySubstring — opsx-loop.model-config-subcommand", () => {
	const catalog = ["anthropic/claude-sonnet-5", "cursor/composer-2.5-fast", "anthropic/claude-opus-4-8"];
	test("substring matches mid-id (claude in anthropic/claude-sonnet-5)", () => {
		expect(filterCatalogBySubstring(catalog, "claude")).toEqual([
			"anthropic/claude-sonnet-5",
			"anthropic/claude-opus-4-8",
		]);
	});
	test("startsWith-only would miss mid-id; contains keeps it", () => {
		const mid = filterCatalogBySubstring(catalog, "sonnet");
		expect(mid).toContain("anthropic/claude-sonnet-5");
		expect(mid).not.toContain("cursor/composer-2.5-fast");
	});
	test("empty filter returns full catalog", () => {
		expect(filterCatalogBySubstring(catalog, "")).toEqual(catalog);
	});
});

describe("fetchModelsCatalog — opsx-loop.model-config-subcommand", () => {
	test("spawn error → actionable message", () => {
		const r = fetchModelsCatalog(() => ({
			status: null,
			stdout: "",
			stderr: "",
			error: new Error("ENOENT"),
		}));
		expect(r.ok).toBe(false);
		if (!r.ok) expect(r.error).toContain("failed to run");
	});
	test("empty parse → actionable message", () => {
		const r = fetchModelsCatalog(() => ({
			status: 0,
			stdout: "provider model\n",
			stderr: "",
		}));
		expect(r.ok).toBe(false);
		if (!r.ok) expect(r.error).toContain("no parseable models");
	});
	test("non-zero exit → actionable message", () => {
		const r = fetchModelsCatalog(() => ({
			status: 2,
			stdout: "",
			stderr: "pi missing",
		}));
		expect(r.ok).toBe(false);
		if (!r.ok) expect(r.error).toMatch(/pi --list-models/);
	});
});

describe("classifyModelsCommand — opsx-loop.model-config-subcommand", () => {
	test("bare models → list", () => {
		expect(classifyModelsCommand([])).toEqual({ kind: "list" });
	});
	test("models list/get → passthrough", () => {
		expect(classifyModelsCommand(["list"])).toEqual({ kind: "passthrough", args: ["list"] });
		expect(classifyModelsCommand(["get", "author"])).toEqual({
			kind: "passthrough",
			args: ["get", "author"],
		});
	});
	test("bare set → interactive", () => {
		expect(classifyModelsCommand(["set"])).toEqual({ kind: "interactive-set" });
	});
	test("role-only set → interactive with role", () => {
		expect(classifyModelsCommand(["set", "review"])).toEqual({
			kind: "interactive-set",
			role: "review",
		});
	});
	test("value-bearing set → passthrough", () => {
		expect(classifyModelsCommand(["set", "author", "anthropic/claude-sonnet-5"])).toEqual({
			kind: "passthrough",
			args: ["set", "author", "anthropic/claude-sonnet-5"],
		});
		expect(classifyModelsCommand(["set", "review", "a:high", "b:xhigh"])).toEqual({
			kind: "passthrough",
			args: ["set", "review", "a:high", "b:xhigh"],
		});
	});
	test("unknown role with value → passthrough (CLI errors)", () => {
		expect(classifyModelsCommand(["set", "nope", "x"])).toEqual({
			kind: "passthrough",
			args: ["set", "nope", "x"],
		});
	});
});

describe("shouldRunInteractiveModelsSet — opsx-loop.model-config-subcommand", () => {
	test("interactive route + hasUI + custom → true", () => {
		expect(
			shouldRunInteractiveModelsSet({ kind: "interactive-set", role: "review" }, true, true),
		).toBe(true);
	});
	test("no UI → false (thin passthrough, no hang)", () => {
		expect(shouldRunInteractiveModelsSet({ kind: "interactive-set" }, false, true)).toBe(false);
	});
	test("no custom ui → false", () => {
		expect(shouldRunInteractiveModelsSet({ kind: "interactive-set" }, true, false)).toBe(false);
	});
	test("passthrough route → false", () => {
		expect(
			shouldRunInteractiveModelsSet({ kind: "passthrough", args: ["set"] }, true, true),
		).toBe(false);
	});
});

describe("appendThinkingSuffix + planInteractiveSetCliArgs — opsx-loop.model-config-subcommand", () => {
	test("skip/off/none leave id bare", () => {
		expect(appendThinkingSuffix("anthropic/a", "skip")).toBe("anthropic/a");
		expect(appendThinkingSuffix("anthropic/a", "off")).toBe("anthropic/a");
	});
	test("appends :level when applicable", () => {
		expect(appendThinkingSuffix("anthropic/a", "high")).toBe("anthropic/a:high");
	});
	test("does not double-suffix", () => {
		expect(appendThinkingSuffix("anthropic/a:high", "xhigh")).toBe("anthropic/a:high");
	});
	test("review mixed per-model suffixes → distinct argv entries", () => {
		const plan = planInteractiveSetCliArgs({
			role: "review",
			reviewModels: ["anthropic/a:high", "anthropic/b:xhigh"],
		});
		expect(plan.ok).toBe(true);
		if (plan.ok) {
			expect(plan.cliArgs).toEqual(["set", "review", "anthropic/a:high", "anthropic/b:xhigh"]);
		}
	});
	test("author scalar with suffix", () => {
		const plan = planInteractiveSetCliArgs({
			role: "author",
			scalarModel: "cursor/composer-2.5-fast:medium",
		});
		expect(plan.ok).toBe(true);
		if (plan.ok) {
			expect(plan.cliArgs).toEqual(["set", "author", "cursor/composer-2.5-fast:medium"]);
		}
	});
	test("author-in-session boolean argv", () => {
		const plan = planInteractiveSetCliArgs({ role: "author-in-session", authorInSession: false });
		expect(plan.ok).toBe(true);
		if (plan.ok) expect(plan.cliArgs).toEqual(["set", "author-in-session", "false"]);
	});
	test("empty review selection → cancelled", () => {
		const plan = planInteractiveSetCliArgs({ role: "review", reviewModels: [] });
		expect(plan.ok).toBe(false);
	});
});

describe("buildModelsSetCliArgs — opsx-loop.model-config-subcommand", () => {
	test("preserves order for multi review ids", () => {
		expect(buildModelsSetCliArgs("review", ["a:high", "b:xhigh", "c"])).toEqual([
			"set",
			"review",
			"a:high",
			"b:xhigh",
			"c",
		]);
	});
});
