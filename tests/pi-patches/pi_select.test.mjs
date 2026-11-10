// node --test tests/pi-patches/pi_select.test.mjs   (no Pi install, no network; temp dirs only)
import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { seriesOf, selectPayload } from "../../dot_local/share/pi-patches/pi-select.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "../..");
const PATCHES = join(ROOT, "dot_local/share/pi-patches");
const VARIANTS = { "1.1": "patch.pi-1.1.mjs", "1.2": "patch.pi-1.2.mjs", "1.3": "patch.pi-1.3.mjs" };
const FOUR = ["headless-extension-drain", "prompt-start-race", "settlement-abort", "standing-reminder-origin"];
// Pi 1.5.1 changed anchors inside the 1.5 series: these two (and btw-native-session) have a full-version floor payload.
const FROM_151 = ["prompt-start-race", "standing-reminder-origin"];
// Real payload maps: a payload serves its series and every later one until a newer payload exists.
const REAL = {
	...Object.fromEntries(FOUR.map((name) => [name, { "1.1": "patch.pi-1.1.mjs", "1.2": "patch.pi-1.2.mjs", ...(FROM_151.includes(name) ? { "1.5.1": "patch.pi-1.5.1.mjs" } : {}) }])),
	"btw-native-session": { "1.1": "patch.pi-1.1.mjs", "1.2": "patch.pi-1.2.mjs", "1.3": "patch.pi-1.3.mjs", "1.4": "patch.pi-1.4.mjs", "1.5": "patch.pi-1.5.mjs", "1.5.1": "patch.pi-1.5.1.mjs" },
};

test("seriesOf: minor series only, strict semver shape", () => {
	assert.equal(seriesOf("1.1.0"), "1.1"); assert.equal(seriesOf("1.2.9"), "1.2"); assert.equal(seriesOf(" 1.2.0 "), "1.2");
	assert.equal(seriesOf("1.2.0-beta.1"), "1.2"); assert.equal(seriesOf("1.10.0"), "1.10");
	for (const bad of ["", "banana", "1.2", "v1.2.0", "1.2.x", undefined, null, 12]) assert.equal(seriesOf(bad), undefined, String(bad));
});

test("selectPayload: version floor (newest payload <= installed), older-than-all unsupported, unparseable, unreadable, not installed -> newest", () => {
	const at = (v) => selectPayload("/x", VARIANTS, () => v);
	assert.deepEqual([at("1.1.0").kind, at("1.1.0").file], ["match", "patch.pi-1.1.mjs"]);
	assert.deepEqual([at("1.2.0").kind, at("1.2.0").file], ["match", "patch.pi-1.2.mjs"]);
	assert.deepEqual([at("1.3.0").kind, at("1.3.0").file], ["match", "patch.pi-1.3.mjs"]);
	assert.equal(at("1.1.7").file, "patch.pi-1.1.mjs");
	for (const v of ["1.4.0", "1.10.0", "1.12.0", "2.0.0"]) assert.deepEqual([at(v).kind, at(v).file], ["match", "patch.pi-1.3.mjs"], v);
	for (const v of ["1.0.0", "0.99.2"]) assert.equal(at(v).kind, "unsupported", v);
	assert.equal(at("banana").kind, "unparseable");
	assert.equal(selectPayload("/x", VARIANTS, () => { throw new Error("ENOENT"); }).kind, "unreadable");
	const none = selectPayload(undefined, VARIANTS);
	assert.deepEqual([none.kind, none.file], ["not-installed", "patch.pi-1.3.mjs"]);
	assert.deepEqual(none.supported, ["1.3", "1.2", "1.1"]);
});

test("selectPayload: a full-version floor (1.5.1) serves that version and later; the series floor below it keeps 1.5.0", () => {
	const v = { "1.2": "patch.pi-1.2.mjs", "1.5": "patch.pi-1.5.mjs", "1.5.1": "patch.pi-1.5.1.mjs" };
	const at = (version) => selectPayload("/x", v, () => version).file;
	assert.equal(at("1.4.0"), "patch.pi-1.2.mjs"); assert.equal(at("1.5.0"), "patch.pi-1.5.mjs");
	for (const version of ["1.5.1", "1.5.2", "1.5.10", "1.6.0", "2.0.0"]) assert.equal(at(version), "patch.pi-1.5.1.mjs", version);
	assert.deepEqual(selectPayload("/x", v, () => "1.5.2").supported, ["1.5.1", "1.5", "1.2"]);
	assert.equal(selectPayload(undefined, v).file, "patch.pi-1.5.1.mjs");
});

function sandbox() {
	const dir = mkdtempSync(join(tmpdir(), "pi-select-test-"));
	copyFileSync(join(PATCHES, "pi-select.mjs"), join(dir, "pi-select.mjs"));
	copyFileSync(join(PATCHES, "pi-root.mjs"), join(dir, "pi-root.mjs"));
	const pd = join(dir, "demo"); mkdirSync(pd);
	for (const [series, code] of [["1.1", 11], ["1.2", 12], ["1.3", 13]]) {
		writeFileSync(join(pd, `patch.pi-${series}.mjs`), `console.log("RAN ${series} args=" + JSON.stringify(process.argv.slice(2)) + " root=" + (process.env.PI_ROOT ?? "")); process.exit(${code});\n`);
	}
	writeFileSync(join(pd, "patch.mjs"), `import { dispatchByPiVersion } from "../pi-select.mjs";\ndispatchByPiVersion(import.meta.url, { name: "demo", packageEnv: "PI_DEMO_PACKAGE", variants: ${JSON.stringify(VARIANTS)} });\n`);
	const pi = (v) => { const r = mkdtempSync(join(dir, "pi-")); writeFileSync(join(r, "package.json"), JSON.stringify({ version: v })); return r; };
	const run = (env, ...args) => { const r = spawnSync(process.execPath, [join(pd, "patch.mjs"), ...args], { encoding: "utf8", env: { PATH: process.env.PATH, HOME: dir, ...env } }); return { code: r.status, out: r.stdout, err: r.stderr }; };
	return { dir, pi, run };
}

test("dispatcher end to end: picks the payload, forwards argv, propagates its exit code, fails loudly otherwise", () => {
	const s = sandbox();
	try {
		let r = s.run({ PI_ROOT: s.pi("1.1.0") }, "--check");
		assert.equal(r.code, 11); assert.match(r.out, /RAN 1\.1 args=\["--check"\]/); assert.match(r.out, /Pi 1\.1\.0 -> payload patch\.pi-1\.1\.mjs/);
		r = s.run({ PI_ROOT: s.pi("1.2.0") }); assert.equal(r.code, 12); assert.match(r.out, /RAN 1\.2 args=\[\]/);
		r = s.run({ PI_ROOT: s.pi("1.3.0") }); assert.equal(r.code, 13); assert.match(r.out, /RAN 1\.3 args=\[\]/);
		r = s.run({ PI_ROOT: s.pi("1.4.0") }); assert.equal(r.code, 13, "a newer Pi runs the newest payload; its anchors decide"); assert.match(r.out, /Pi 1\.4\.0 -> payload patch\.pi-1\.3\.mjs/);
		r = s.run({ PI_ROOT: s.pi("1.0.0") }); assert.equal(r.code, 1, "an older Pi must not silently use a newer payload");
		assert.doesNotMatch(r.out, /RAN/); assert.match(r.err, /no payload for Pi 1\.0\.0; payloads start at Pi 1\.1\.x/);
		r = s.run({ PI_ROOT: s.pi("banana") }); assert.equal(r.code, 1); assert.match(r.err, /unrecognised Pi version "banana"/);
		const noPkg = mkdtempSync(join(s.dir, "empty-")); r = s.run({ PI_ROOT: noPkg });
		assert.equal(r.code, 1); assert.match(r.err, /cannot read Pi version/);
		r = s.run({ PI_ROOT: s.pi("1.1.0"), PI_DEMO_PACKAGE: s.pi("1.2.0") }); assert.equal(r.code, 12, "the per-patch package override wins over PI_ROOT, like the payloads");
		r = s.run({ HOME: s.dir, PI_CODING_AGENT_DIR: join(s.dir, "none"), PATH: "/usr/bin:/bin" });
		assert.equal(r.code, 13); assert.equal(r.out, "RAN 1.3 args=[] root=\n", "no Pi: the dispatcher prints nothing; the newest payload runs and prints its own notice");
	} finally { rmSync(s.dir, { recursive: true, force: true }); }
});

test("mutant guard: a missing payload file is a loud failure, not a skip", () => {
	const s = sandbox();
	try { rmSync(join(s.dir, "demo", "patch.pi-1.1.mjs")); const r = s.run({ PI_ROOT: s.pi("1.1.0") }); assert.equal(r.code, 1); assert.match(r.err, /payload patch\.pi-1\.1\.mjs is missing/); }
	finally { rmSync(s.dir, { recursive: true, force: true }); }
});

test("repository wiring: every dispatching patch has both payloads, the real dispatcher variants map matches, and the onchange script hashes every file", () => {
	const tmpl = readFileSync(join(ROOT, "run_onchange_after_30_apply_pi_patches.sh.tmpl"), "utf8");
	assert.ok(tmpl.includes('include "dot_local/share/pi-patches/pi-select.mjs" | sha256sum'));
	for (const [name, VARIANTS] of Object.entries(REAL)) {
		const dir = join(PATCHES, name);
		const entry = readFileSync(join(dir, "patch.mjs"), "utf8");
		assert.match(entry, /dispatchByPiVersion/); assert.match(entry, new RegExp(`name: "${name}"`));
		for (const file of Object.values(VARIANTS)) {
			assert.ok(existsSync(join(dir, file)), `${name}/${file} exists`);
			assert.ok(entry.includes(`"${file}"`), `${name}/patch.mjs maps ${file}`);
			assert.ok(tmpl.includes(`include "dot_local/share/pi-patches/${name}/${file}" | sha256sum`), `onchange hashes ${name}/${file}`);
		}
		assert.ok(tmpl.includes(`include "dot_local/share/pi-patches/${name}/patch.mjs" | sha256sum`));
		assert.deepEqual(readdirSync(dir).filter((f) => /^patch\.pi-.*\.mjs$/.test(f)).sort(), Object.values(VARIANTS).sort(), `${name}: no unmapped payload files`);
	}
});

// The real btw-native-session entry point against package.json-only roots. The payload then fails (there are no bundle chunks), but the
// dispatcher's own line says which payload it chose, which is what is under test. Older than every payload, unparseable: loud exit 1, nothing run.
test("real btw-native-session selector: 1.1 to 1.5.0 each pick their own payload, 1.5.1 and later pick the 1.5.1 payload, unsupported and unparseable fail loudly", () => {
	const dir = mkdtempSync(join(tmpdir(), "pi-btw-select-"));
	try {
		const pi = (v) => { const r = mkdtempSync(join(dir, "pi-")); writeFileSync(join(r, "package.json"), JSON.stringify({ version: v })); return r; };
		const run = (v) => spawnSync(process.execPath, [join(PATCHES, "btw-native-session/patch.mjs"), "--check"], { encoding: "utf8", env: { PATH: process.env.PATH, HOME: dir, PI_ROOT: pi(v), PI_CHEZMOI_PROFILE: "personal" } });
		const expected = { "1.1.0": "1.1", "1.1.9": "1.1", "1.2.0": "1.2", "1.3.0": "1.3", "1.4.0": "1.4", "1.4.7": "1.4", "1.5.0": "1.5", "1.5.1": "1.5.1", "1.5.2": "1.5.1", "1.5.3": "1.5.1", "1.6.0": "1.5.1", "2.0.0": "1.5.1" };
		for (const [version, series] of Object.entries(expected)) {
			const r = run(version);
			assert.match(r.stdout, new RegExp(`Pi ${version.replace(/\./g, "\\.")} -> payload patch\\.pi-${series.replace(".", "\\.")}\\.mjs`), `${version} -> ${series}`);
		}
		let r = run("1.0.0"); assert.equal(r.status, 1); assert.doesNotMatch(r.stdout, /payload/); assert.match(r.stderr, /no payload for Pi 1\.0\.0; payloads start at Pi 1\.1\.x/);
		r = run("banana"); assert.equal(r.status, 1); assert.doesNotMatch(r.stdout, /payload/); assert.match(r.stderr, /unrecognised Pi version "banana"/);
	} finally { rmSync(dir, { recursive: true, force: true }); }
});

test("btw-native-session edits: every payload's edits file is hashed by the onchange script, and edits.pi-1.5.json differs from 1.4 only in the four edits Pi 1.5.0 forced (plus chunk-name hints)", () => {
	const tmpl = readFileSync(join(ROOT, "run_onchange_after_30_apply_pi_patches.sh.tmpl"), "utf8");
	const dir = join(PATCHES, "btw-native-session");
	for (const f of ["edits.json", "edits.pi-1.2.json", "edits.pi-1.3.json", "edits.pi-1.4.json", "edits.pi-1.5.json", "edits.pi-1.5.1.json"]) {
		assert.ok(existsSync(join(dir, f)), f);
		assert.ok(tmpl.includes(`include "dot_local/share/pi-patches/btw-native-session/${f}" | sha256sum`), `onchange hashes ${f}`);
	}
	const load = (f) => JSON.parse(readFileSync(join(dir, f), "utf8"));
	const [e4, e5] = [load("edits.pi-1.4.json"), load("edits.pi-1.5.json")];
	assert.equal(e5.length, e4.length);
	const changed = e5.map((e, i) => (e.old !== e4[i].old || e.new !== e4[i].new ? i : -1)).filter((i) => i >= 0);
	assert.deepEqual(changed, [2, 15, 30, 99]);
	for (const i of changed) assert.notEqual(e5[i].old, e5[i].new);
	for (const [i, e] of e5.entries()) assert.equal(e.package, e4[i].package);
	for (const e of e5) assert.ok(!e.path.includes("chunk-MM3LKT73") && !e.path.includes("chunk-T726RZZU"), "chunk hints are the 1.5.0 names");
});
