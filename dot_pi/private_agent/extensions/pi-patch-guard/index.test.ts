// Tests for the pi-patch-guard pure helpers.
// Run: node --test dot_pi/agent/extensions/pi-patch-guard/index.test.ts
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import {
	checkAssumption,
	checkPatchDrift,
	discoverWatchedPatches,
	loadAssumptions,
	loadConfig,
	resolvePiDistDir,
} from "./index.ts";

const PATCH = {
	name: "hide-nonbridge-claude-models",
	marker: "chezmoi-pi-patch:hide-nonbridge-claude-models",
};

function tmp(): string {
	return fs.mkdtempSync(path.join(os.tmpdir(), "patch-guard-test-"));
}

function writeState(stateDir: string, obj: unknown): void {
	fs.mkdirSync(stateDir, { recursive: true });
	fs.writeFileSync(path.join(stateDir, `${PATCH.name}.json`), JSON.stringify(obj));
}

test("no state file ⇒ no drift", () => {
	const dir = tmp();
	const r = checkPatchDrift(PATCH, { stateDir: path.join(dir, "missing") });
	assert.equal(r.drift, false);
});

test("status patched + marker present ⇒ no drift", () => {
	const dir = tmp();
	const target = path.join(dir, "model-registry.js");
	fs.writeFileSync(target, `// ${PATCH.marker}\nfunction getAvailable(){}`);
	writeState(dir, { status: "patched", target });
	const r = checkPatchDrift(PATCH, { stateDir: dir });
	assert.equal(r.drift, false);
});

test("status patched + marker MISSING ⇒ drift", () => {
	const dir = tmp();
	const target = path.join(dir, "model-registry.js");
	fs.writeFileSync(target, `function getAvailable(){ return all; }`); // wiped by update
	writeState(dir, { status: "patched", target });
	const r = checkPatchDrift(PATCH, { stateDir: dir });
	assert.equal(r.drift, true);
	assert.equal(r.upstream, false);
	assert.equal(r.name, PATCH.name);
});

test("status unpatched (profile≠personal) ⇒ no drift even if marker absent", () => {
	const dir = tmp();
	const target = path.join(dir, "model-registry.js");
	fs.writeFileSync(target, `function getAvailable(){ return all; }`);
	writeState(dir, { status: "unpatched", target });
	const r = checkPatchDrift(PATCH, { stateDir: dir });
	assert.equal(r.drift, false);
});

test("status already-patched counts as intended-on", () => {
	const dir = tmp();
	const target = path.join(dir, "model-registry.js");
	fs.writeFileSync(target, `function getAvailable(){ return all; }`);
	writeState(dir, { status: "already-patched", target });
	const r = checkPatchDrift(PATCH, { stateDir: dir });
	assert.equal(r.drift, true);
});

test("target path no longer exists ⇒ no drift (ambiguous, stay quiet)", () => {
	const dir = tmp();
	writeState(dir, { status: "patched", target: path.join(dir, "gone.js") });
	const r = checkPatchDrift(PATCH, { stateDir: dir });
	assert.equal(r.drift, false);
});

test("malformed state json ⇒ no drift", () => {
	const dir = tmp();
	fs.mkdirSync(dir, { recursive: true });
	fs.writeFileSync(path.join(dir, `${PATCH.name}.json`), "{ not json");
	const r = checkPatchDrift(PATCH, { stateDir: dir });
	assert.equal(r.drift, false);
});

test("discover: derives name + marker from each state file", () => {
	const dir = tmp();
	fs.mkdirSync(dir, { recursive: true });
	fs.writeFileSync(path.join(dir, "custom-message-marker.json"), JSON.stringify({ status: "patched", patchName: "custom-message-marker" }));
	fs.writeFileSync(path.join(dir, "hide-nonbridge-claude-models.json"), JSON.stringify({ status: "unpatched" }));
	const found = discoverWatchedPatches({ stateDir: dir }).sort((a, b) => a.name.localeCompare(b.name));
	assert.deepEqual(found, [
		{ name: "custom-message-marker", marker: "chezmoi-pi-patch:custom-message-marker" },
		{ name: "hide-nonbridge-claude-models", marker: "chezmoi-pi-patch:hide-nonbridge-claude-models" },
	]);
});

test("discover: honors explicit marker override in state file", () => {
	const dir = tmp();
	fs.mkdirSync(dir, { recursive: true });
	fs.writeFileSync(path.join(dir, "custom.json"), JSON.stringify({ status: "patched", patchName: "custom", marker: "custom-sentinel" }));
	assert.deepEqual(discoverWatchedPatches({ stateDir: dir }), [{ name: "custom", marker: "custom-sentinel" }]);
});

test("discover: name falls back to filename when patchName absent; ignores non-json", () => {
	const dir = tmp();
	fs.mkdirSync(dir, { recursive: true });
	fs.writeFileSync(path.join(dir, "foo.json"), JSON.stringify({ status: "patched" }));
	fs.writeFileSync(path.join(dir, "README.md"), "not a state file");
	assert.deepEqual(discoverWatchedPatches({ stateDir: dir }), [{ name: "foo", marker: "chezmoi-pi-patch:foo" }]);
});

test("discover: missing state dir ⇒ [] (quiet)", () => {
	const dir = tmp();
	assert.deepEqual(discoverWatchedPatches({ stateDir: path.join(dir, "nope") }), []);
});

test("loadConfig: missing ⇒ enabled; enabled:false ⇒ disabled", () => {
	const dir = tmp();
	assert.equal(loadConfig(dir).enabled, true);
	fs.writeFileSync(path.join(dir, "config.json"), JSON.stringify({ enabled: false }));
	assert.equal(loadConfig(dir).enabled, false);
});

// --- source assumptions (sentinels) ------------------------------------------

const ASSUMPTION = {
	name: "example-call-order",
	file: "core/example.js",
	pattern: "async run\\(\\)\\s*\\{\\s*this\\.prepare\\(\\);\\s*await this\\.execute\\(\\);",
	message: "recheck dependent extension",
};

function writeDist(body: string): string {
	const dist = path.join(tmp(), "dist");
	fs.mkdirSync(path.join(dist, "core"), { recursive: true });
	fs.writeFileSync(path.join(dist, "core", "example.js"), body);
	return dist;
}

test("assumption holds when calls retain expected order", () => {
	const dist = writeDist(
		"    async run() {\n        this.prepare();\n        await this.execute();\n    }\n",
	);
	assert.equal(checkAssumption(ASSUMPTION, { distDir: dist }).broken, false);
});

test("assumption BREAKS when pi reorders calls", () => {
	const dist = writeDist(
		"    async run() {\n        await this.execute();\n        this.prepare();\n    }\n",
	);
	const r = checkAssumption(ASSUMPTION, { distDir: dist });
	assert.equal(r.broken, true);
	assert.equal(r.name, ASSUMPTION.name);
});

test("assumption BREAKS when pi drops a required call", () => {
	const dist = writeDist("    async run() {\n        await this.execute();\n    }\n");
	assert.equal(checkAssumption(ASSUMPTION, { distDir: dist }).broken, true);
});

test("assumption: missing file or unresolvable dist ⇒ quiet (not broken)", () => {
	const dist = path.join(tmp(), "dist");
	assert.equal(checkAssumption(ASSUMPTION, { distDir: dist }).broken, false);
	assert.equal(checkAssumption(ASSUMPTION, { distDir: undefined, exists: () => false }).broken, false);
});

test("assumption: invalid regex ⇒ quiet", () => {
	const dist = writeDist("whatever");
	assert.equal(checkAssumption({ ...ASSUMPTION, pattern: "([" }, { distDir: dist }).broken, false);
});

test("loadAssumptions: reads assumptions.json, drops malformed entries", () => {
	const dir = tmp();
	fs.writeFileSync(
		path.join(dir, "assumptions.json"),
		JSON.stringify({ assumptions: [ASSUMPTION, { name: "bad" }, { file: "x", pattern: "y" }] }),
	);
	const found = loadAssumptions(dir);
	assert.equal(found.length, 1);
	assert.equal(found[0]?.name, ASSUMPTION.name);
});

test("loadAssumptions: missing/malformed file ⇒ []", () => {
	const dir = tmp();
	assert.deepEqual(loadAssumptions(dir), []);
	fs.writeFileSync(path.join(dir, "assumptions.json"), "{ not json");
	assert.deepEqual(loadAssumptions(dir), []);
});

test("shipped assumptions.json has no obsolete source sentinels", () => {
	const shipped = loadAssumptions(path.dirname(fileURLToPath(import.meta.url)));
	assert.deepEqual(shipped, []);
});

test("resolvePiDistDir: finds the running pi cli in argv", () => {
	const cli = path.join("/opt", "node_modules", "@earendil-works", "pi-coding-agent", "dist", "cli.js");
	const dist = path.dirname(cli);
	assert.equal(
		resolvePiDistDir({ argv: ["/bin/node", cli], execPath: "/bin/node", exists: (p) => p === dist }),
		dist,
	);
});

test("resolvePiDistDir: falls back to the global npm root beside node", () => {
	const dist = path.join("/n", "lib", "node_modules", "@earendil-works", "pi-coding-agent", "dist");
	assert.equal(resolvePiDistDir({ argv: ["/n/bin/node"], execPath: "/n/bin/node", exists: (p) => p === dist }), dist);
});

test("resolvePiDistDir: nothing resolvable ⇒ undefined (quiet)", () => {
	assert.equal(resolvePiDistDir({ argv: ["/n/bin/node"], execPath: "/n/bin/node", exists: () => false }), undefined);
});

const ASTRA = {
	name: "openai-codex-gpt-6-astra",
	marker: "chezmoi-pi-patch:openai-codex-gpt-6-astra v2",
};

test("catalogStopgap: marker gone + id still in target ⇒ upstream, not wipe", () => {
	const dir = tmp();
	const target = path.join(dir, "chunk.js");
	fs.mkdirSync(dir, { recursive: true });
	fs.writeFileSync(target, `var openai_codex_default={"gpt-6-astra":{id:"gpt-6-astra"}};`);
	fs.writeFileSync(
		path.join(dir, `${ASTRA.name}.json`),
		JSON.stringify({
			status: "patched",
			target,
			catalogStopgap: { provider: "openai-codex", id: "gpt-6-astra" },
			chezmoiSource: "dot_local/share/pi-patches/openai-codex-gpt-6-astra",
		}),
	);
	const r = checkPatchDrift(ASTRA, { stateDir: dir });
	assert.equal(r.drift, false);
	assert.equal(r.upstream, true);
	assert.equal(r.catalogId, "gpt-6-astra");
	assert.equal(r.chezmoiSource, "dot_local/share/pi-patches/openai-codex-gpt-6-astra");
});

test("catalogStopgap: marker gone + id missing ⇒ wipe (re-apply)", () => {
	const dir = tmp();
	const target = path.join(dir, "chunk.js");
	fs.mkdirSync(dir, { recursive: true });
	fs.writeFileSync(target, `var openai_codex_default={"gpt-5.5":{id:"gpt-5.5"}};`);
	fs.writeFileSync(
		path.join(dir, `${ASTRA.name}.json`),
		JSON.stringify({
			status: "patched",
			target,
			catalogStopgap: { provider: "openai-codex", id: "gpt-6-astra" },
		}),
	);
	const r = checkPatchDrift(ASTRA, { stateDir: dir });
	assert.equal(r.drift, true);
	assert.equal(r.upstream, false);
});

test("catalogStopgap: marker present + id present ⇒ keep (our insert)", () => {
	const dir = tmp();
	const target = path.join(dir, "chunk.js");
	fs.mkdirSync(dir, { recursive: true });
	fs.writeFileSync(
		target,
		`/*${ASTRA.marker}*/var openai_codex_default={"gpt-6-astra":{id:"gpt-6-astra"}};`,
	);
	fs.writeFileSync(
		path.join(dir, `${ASTRA.name}.json`),
		JSON.stringify({
			status: "patched",
			target,
			catalogStopgap: { provider: "openai-codex", id: "gpt-6-astra" },
		}),
	);
	const r = checkPatchDrift(ASTRA, { stateDir: dir });
	assert.equal(r.drift, false);
	assert.equal(r.upstream, false);
});
