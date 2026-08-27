// Tests for the openrouter-gate pure helpers.
// Run from this directory: node --test
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import {
	buildAllowedModels,
	catalogIdsFor,
	describeConfig,
	fallbackModel,
	filterModels,
	isGlobPattern,
	isProviderOpen,
	loadConfig,
	modelAllowed,
	normalizeConfig,
	saveConfig,
} from "./config.ts";
import { parseSubcommand, readStash, catalogSignature } from "./index.ts";
import {
	addAllowedModel,
	commandCompletions,
	fetchOpenRouterModels,
	getCachedPickerModels,
	mergePickerModels,
	normalizeAllowId,
	parseCommand,
	parseModelsResponse,
	pickerItemsExcluding,
	rankPickerModels,
	rememberPickerModels,
	removeAllowedModel,
	resetPickerCache,
} from "./catalog.ts";

const AUTH_PATH = "/fake/auth.json";

function reader(obj: unknown): { readFile: (p: string) => string; authPath: string } {
	return {
		readFile: (p) => {
			assert.equal(p, AUTH_PATH);
			return JSON.stringify(obj);
		},
		authPath: AUTH_PATH,
	};
}

function model(id: string, name = id) {
	return {
		id,
		name,
		reasoning: true,
		input: ["text"] as Array<"text" | "image">,
		cost: { input: 1, output: 2, cacheRead: 0, cacheWrite: 0 },
		contextWindow: 128000,
		maxTokens: 16384,
		api: "openai-completions",
		baseUrl: "https://openrouter.ai/api/v1",
	};
}

test("readStash: stash present with key", () => {
	const s = readStash(reader({ "openrouter-stashed": { type: "api_key", key: "sk-or-v1-abc" } }));
	assert.equal(s.key, "sk-or-v1-abc");
	assert.equal(s.stashPresent, true);
	assert.equal(s.liveEntryPresent, false);
	assert.equal(s.error, undefined);
});

test("readStash: stash present but malformed (no key)", () => {
	const s = readStash(reader({ "openrouter-stashed": { type: "api_key" } }));
	assert.equal(s.key, undefined);
	assert.equal(s.stashPresent, true);
});

test("readStash: empty-string key is unusable", () => {
	const s = readStash(reader({ "openrouter-stashed": { key: "" } }));
	assert.equal(s.key, undefined);
	assert.equal(s.stashPresent, true);
});

test("readStash: live openrouter entry detected (gate bypassed)", () => {
	const s = readStash(reader({ openrouter: { type: "api_key", key: "sk-or-v1-live" } }));
	assert.equal(s.liveEntryPresent, true);
	assert.equal(s.stashPresent, false);
	assert.equal(s.key, undefined);
});

test("readStash: both live and stash present", () => {
	const s = readStash(
		reader({
			openrouter: { type: "api_key", key: "live" },
			"openrouter-stashed": { type: "api_key", key: "stashed" },
		}),
	);
	assert.equal(s.liveEntryPresent, true);
	assert.equal(s.stashPresent, true);
	assert.equal(s.key, "stashed");
});

test("readStash: missing file reports error, never throws", () => {
	const s = readStash({
		readFile: () => {
			throw new Error("ENOENT");
		},
		authPath: AUTH_PATH,
	});
	assert.equal(s.stashPresent, false);
	assert.equal(s.liveEntryPresent, false);
	assert.match(s.error ?? "", /ENOENT/);
});

test("readStash: malformed json reports error, never throws", () => {
	const s = readStash({ readFile: () => "{not json", authPath: AUTH_PATH });
	assert.equal(s.stashPresent, false);
	assert.ok(s.error);
});

test("parseSubcommand: canonical values", () => {
	assert.equal(parseSubcommand("on"), "on");
	assert.equal(parseSubcommand(" OFF "), "off");
	assert.equal(parseSubcommand("status"), "status");
	assert.equal(parseSubcommand("reload"), "reload");
	assert.equal(parseSubcommand("allow"), "allow");
	assert.equal(parseSubcommand("deny z-ai/glm-5.3-flash"), "deny");
	assert.equal(parseSubcommand(""), "status");
	assert.equal(parseSubcommand("bogus"), "help");
});

test("normalizeConfig: defaults, omitted allowlist, explicit empty, trim/dedupe", () => {
	assert.deepEqual(normalizeConfig(undefined), {
		enabled: false,
		allowedModels: ["z-ai/glm-5.3-flash"],
	});
	assert.deepEqual(normalizeConfig({ enabled: true }), {
		enabled: true,
		allowedModels: ["z-ai/glm-5.3-flash"],
	});
	assert.deepEqual(normalizeConfig({ enabled: true, allowedModels: [] }), {
		enabled: true,
		allowedModels: [],
	});
	assert.deepEqual(
		normalizeConfig({
			enabled: false,
			allowedModels: [" z-ai/glm-5.3-flash ", "", "z-ai/glm-5.3", "z-ai/glm-5.3-flash", 12],
		}),
		{ enabled: false, allowedModels: ["z-ai/glm-5.3-flash", "z-ai/glm-5.3"] },
	);
});

test("isProviderOpen: enabled and non-empty allowlist only", () => {
	assert.equal(isProviderOpen({ enabled: false, allowedModels: ["z-ai/glm-5.3-flash"] }), false);
	assert.equal(isProviderOpen({ enabled: true, allowedModels: [] }), false);
	assert.equal(isProviderOpen({ enabled: true, allowedModels: ["z-ai/glm-5.3-flash"] }), true);
});

test("modelAllowed: exact, glob, plus variants, openrouter/ prefix, fail-closed", () => {
	assert.equal(modelAllowed("z-ai/glm-5.3-flash", []), false);
	assert.equal(modelAllowed("z-ai/glm-5.3-flash", ["z-ai/glm-5.3-flash"]), true);
	assert.equal(modelAllowed("z-ai/glm-5.3", ["z-ai/glm-5.3-flash"]), false);
	assert.equal(modelAllowed("z-ai/glm-5.3-flash", ["z-ai/*"]), true);
	assert.equal(modelAllowed("openai/gpt-5", ["z-ai/*"]), false);
	assert.equal(modelAllowed("openrouter/z-ai/glm-5.3-flash", ["z-ai/glm-5.3-flash"]), true);
	assert.equal(modelAllowed("@or:zhipu:fp8:z-ai/glm-5.3-flash", ["z-ai/glm-5.3-flash"]), true);
	assert.equal(modelAllowed("@or:zhipu:z-ai/glm-5.3-flash", ["z-ai/*"]), true);
	assert.equal(modelAllowed("@or:zhipu:fp8:openai/gpt-5", ["z-ai/glm-5.3-flash"]), false);
	assert.equal(isGlobPattern("z-ai/*"), true);
	assert.equal(isGlobPattern("z-ai/glm-5.3-flash"), false);
	assert.deepEqual(catalogIdsFor("@or:zhipu:fp8:z-ai/glm-5.3-flash"), [
		"@or:zhipu:fp8:z-ai/glm-5.3-flash",
		"z-ai/glm-5.3-flash",
	]);
});

test("filterModels and buildAllowedModels: drop others, stub missing exact ids", () => {
	const catalog = [
		model("z-ai/glm-5.3-flash", "GLM 5.3 Flash"),
		model("z-ai/glm-5.3", "GLM 5.3"),
		model("openai/gpt-5", "GPT-5"),
	];
	assert.deepEqual(
		filterModels(catalog, ["z-ai/glm-5.3-flash"]).map((m) => m.id),
		["z-ai/glm-5.3-flash"],
	);
	assert.deepEqual(filterModels(catalog, []), []);

	const fromCatalog = buildAllowedModels(catalog, ["z-ai/glm-5.3-flash"]);
	assert.equal(fromCatalog.length, 1);
	assert.equal(fromCatalog[0]?.id, "z-ai/glm-5.3-flash");
	assert.equal(fromCatalog[0]?.name, "GLM 5.3 Flash");

	const stubbed = buildAllowedModels([], ["z-ai/glm-5.3-flash", "acme/unreleased"]);
	assert.equal(stubbed.length, 2);
	assert.equal(stubbed[0]?.id, "z-ai/glm-5.3-flash");
	assert.equal(stubbed[0]?.name, "Z.ai: GLM 5.3 Flash");
	assert.equal(stubbed[1]?.id, "acme/unreleased");
	assert.equal(stubbed[1]?.name, "acme/unreleased");

	assert.deepEqual(buildAllowedModels(catalog, ["z-ai/*"]).map((m) => m.id), [
		"z-ai/glm-5.3-flash",
		"z-ai/glm-5.3",
	]);
	assert.deepEqual(buildAllowedModels(catalog, []), []);
	assert.equal(fallbackModel("z-ai/glm-5.3-flash").contextWindow, 1_048_576);
});

test("loadConfig/saveConfig round-trip; missing file uses defaults", () => {
	const dir = mkdtempSync(join(tmpdir(), "openrouter-gate-"));
	try {
		const path = join(dir, "config.json");
		assert.deepEqual(loadConfig(path), {
			enabled: false,
			allowedModels: ["z-ai/glm-5.3-flash"],
		});
		saveConfig(path, { enabled: true, allowedModels: ["z-ai/glm-5.3", ""] });
		assert.equal(JSON.parse(readFileSync(path, "utf8")).enabled, true);
		assert.deepEqual(loadConfig(path), { enabled: true, allowedModels: ["z-ai/glm-5.3"] });
	} finally {
		rmSync(dir, { recursive: true, force: true });
	}
});

test("describeConfig: on/off and empty allowlist", () => {
	assert.equal(
		describeConfig({ enabled: false, allowedModels: ["z-ai/glm-5.3-flash"] }),
		"OpenRouter OFF; allowlist: z-ai/glm-5.3-flash",
	);
	assert.equal(
		describeConfig({ enabled: true, allowedModels: [] }),
		"OpenRouter ON; allowlist empty (fail-closed)",
	);
});

test("catalogSignature changes when plus expands the source catalog", () => {
	const config = { enabled: true, allowedModels: ["z-ai/glm-5.3-flash"] };
	const stub = catalogSignature(config, [], ["z-ai/glm-5.3-flash"]);
	const afterPlus = catalogSignature(
		config,
		["z-ai/glm-5.3-flash", "openai/gpt-5"],
		["z-ai/glm-5.3-flash"],
	);
	assert.notEqual(stub, afterPlus);
	assert.equal(
		afterPlus,
		catalogSignature(config, ["z-ai/glm-5.3-flash", "openai/gpt-5"], ["z-ai/glm-5.3-flash"]),
	);
});

test("parseCommand: allow/deny ids, globs, openrouter/ prefix", () => {
	assert.deepEqual(parseCommand(""), { kind: "status" });
	assert.deepEqual(parseCommand("allow"), { kind: "allow", id: undefined });
	assert.deepEqual(parseCommand("allow  openrouter/z-ai/glm-5.3-flash"), {
		kind: "allow",
		id: "z-ai/glm-5.3-flash",
	});
	assert.deepEqual(parseCommand("deny z-ai/*"), { kind: "deny", id: "z-ai/*" });
	assert.equal(normalizeAllowId("openrouter/z-ai/glm-5.3-flash"), "z-ai/glm-5.3-flash");
});

test("parseModelsResponse and merge skip plus variants and nameless junk", () => {
	assert.deepEqual(
		parseModelsResponse({
			data: [
				{ id: "z-ai/glm-5.3-flash", name: "Z.ai: GLM 5.3 Flash" },
				{ id: "@or:zhipu:fp8:z-ai/glm-5.3-flash", name: "variant" },
				{ id: "no-slash" },
				{ id: "z-ai/glm-5.3-flash", name: "dup" },
				{ name: "missing id" },
			],
		}),
		[{ id: "z-ai/glm-5.3-flash", name: "Z.ai: GLM 5.3 Flash" }],
	);
	assert.deepEqual(
		mergePickerModels(
			[{ id: "openai/gpt-5", name: "GPT-5" }],
			[{ id: "z-ai/glm-5.3-flash", name: "GLM" }, { id: "@or:x:openai/gpt-5", name: "x" }],
		).map((m) => m.id),
		["openai/gpt-5", "z-ai/glm-5.3-flash"],
	);
});

test("add/remove allowlist entries; glob-covered models stay out of the picker", () => {
	assert.deepEqual(addAllowedModel([], "openrouter/z-ai/glm-5.3-flash"), {
		allowed: ["z-ai/glm-5.3-flash"],
		added: true,
	});
	assert.equal(addAllowedModel(["z-ai/glm-5.3-flash"], "z-ai/glm-5.3-flash").added, false);
	assert.deepEqual(removeAllowedModel(["z-ai/glm-5.3-flash", "openai/gpt-5"], "z-ai/glm-5.3-flash"), {
		allowed: ["openai/gpt-5"],
		removed: true,
	});
	assert.equal(removeAllowedModel(["z-ai/*"], "z-ai/glm-5.3-flash").removed, false);
	assert.deepEqual(
		pickerItemsExcluding(
			[
				{ id: "z-ai/glm-5.3-flash", name: "flash" },
				{ id: "openai/gpt-5", name: "gpt" },
			],
			["z-ai/*"],
		).map((m) => m.id),
		["openai/gpt-5"],
	);
});

test("commandCompletions: subcommands, allow catalog, typed glob, deny allowlist", () => {
	const catalog = [
		{ id: "z-ai/glm-5.3-flash", name: "Z.ai: GLM 5.3 Flash" },
		{ id: "openai/gpt-5", name: "GPT-5" },
	];
	assert.deepEqual(
		commandCompletions("a", catalog, []).map((item) => item.value),
		["allow "],
	);
	assert.deepEqual(
		commandCompletions("allow ", catalog, ["z-ai/glm-5.3-flash"]).map((item) => item.value),
		["allow openai/gpt-5"],
	);
	const glob = commandCompletions("allow z-ai/*", catalog, []);
	assert.equal(glob[0]?.value, "allow z-ai/*");
	assert.equal(glob[0]?.description, "glob pattern");
	assert.deepEqual(
		commandCompletions("deny ", catalog, ["z-ai/glm-5.3-flash", "openai/gpt-5"]).map((item) => item.label),
		["openai/gpt-5", "z-ai/glm-5.3-flash"],
	);
});

test("rankPickerModels: empty query sorts; tokens match id fragments", () => {
	const ranked = rankPickerModels(
		[
			{ id: "openai/gpt-5", name: "GPT-5" },
			{ id: "z-ai/glm-5.3-flash", name: "Z.ai: GLM 5.3 Flash" },
		],
		"glm flash",
	);
	assert.equal(ranked[0]?.id, "z-ai/glm-5.3-flash");
	assert.deepEqual(
		rankPickerModels(
			[
				{ id: "z-ai/glm-5.3-flash", name: "flash" },
				{ id: "openai/gpt-5", name: "gpt" },
			],
			"",
		).map((m) => m.id),
		["openai/gpt-5", "z-ai/glm-5.3-flash"],
	);
});

test("fetchOpenRouterModels: caches, skips plus variants, throws on HTTP error", async () => {
	resetPickerCache();
	let calls = 0;
	const fetchOk = (async () => {
		calls += 1;
		return {
			ok: true,
			status: 200,
			statusText: "OK",
			json: async () => ({
				data: [
					{ id: "z-ai/glm-5.3-flash", name: "GLM" },
					{ id: "@or:zhipu:fp8:z-ai/glm-5.3-flash", name: "variant" },
				],
			}),
		};
	}) as typeof fetch;
	rememberPickerModels([{ id: "openai/gpt-5", name: "GPT-5" }]);
	const first = await fetchOpenRouterModels({ fetch: fetchOk, now: () => 1_000 });
	assert.deepEqual(
		first.map((m) => m.id),
		["openai/gpt-5", "z-ai/glm-5.3-flash"],
	);
	await fetchOpenRouterModels({ fetch: fetchOk, now: () => 2_000 });
	assert.equal(calls, 1);
	assert.deepEqual(
		getCachedPickerModels().map((m) => m.id),
		["openai/gpt-5", "z-ai/glm-5.3-flash"],
	);

	resetPickerCache();
	const fetchFail = (async () => ({ ok: false, status: 502, statusText: "Bad Gateway" })) as typeof fetch;
	await assert.rejects(() => fetchOpenRouterModels({ fetch: fetchFail, now: () => 1 }), /502/);
});
