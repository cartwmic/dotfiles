// Tests for the pi-patch-guard pure helpers.
// Run: node --test dot_pi/agent/extensions/pi-patch-guard/index.test.ts
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { test } from "node:test";
import { checkPatchDrift, loadConfig } from "./index.ts";

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

test("loadConfig: missing ⇒ enabled; enabled:false ⇒ disabled", () => {
	const dir = tmp();
	assert.equal(loadConfig(dir).enabled, true);
	fs.writeFileSync(path.join(dir, "config.json"), JSON.stringify({ enabled: false }));
	assert.equal(loadConfig(dir).enabled, false);
});
