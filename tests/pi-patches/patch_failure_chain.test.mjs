// node --test tests/pi-patches/patch_failure_chain.test.mjs   (no Pi install, no network; temp dirs only)
// A failed Pi patch must not stop the later chezmoi scripts, must be reported loudly, and must make the apply exit non-zero at the end.
import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { chmodSync, copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "../..");
const APPLY = join(ROOT, "dot_local/user_scripts/executable_apply_pi_patches.sh");
const REPORT = join(ROOT, "run_after_99_report_pi_patch_failures.sh");
const WRAPPER = join(ROOT, "run_onchange_after_30_apply_pi_patches.sh.tmpl");
const sh = (script, env) => spawnSync("/bin/sh", [script], { encoding: "utf8", env: { PATH: process.env.PATH, ...env } });

function sandbox() {
	const dir = mkdtempSync(join(tmpdir(), "pi-failure-chain-"));
	const patches = join(dir, "patches");
	mkdirSync(patches);
	copyFileSync(join(ROOT, "dot_local/share/pi-patches/pi-root.mjs"), join(patches, "pi-root.mjs"));
	const addPatch = (name, body) => { mkdirSync(join(patches, name), { recursive: true }); writeFileSync(join(patches, name, "patch.mjs"), body); };
	const marker = join(dir, "state", "failed");
	const env = { HOME: dir, PI_PATCHES_ROOT: patches, PI_PATCH_FAILURE_MARKER: marker, PI_CODING_AGENT_DIR: join(dir, "none"), PI_PATCH_EXTENSIONS: "" };
	return { dir, patches, addPatch, marker, env, cleanup: () => rmSync(dir, { recursive: true, force: true }) };
}
const touches = (file) => `import { writeFileSync } from "node:fs"; writeFileSync(${JSON.stringify(file)}, "ran");\n`;

test("apply loop: a failing patch does not stop the rest, is named, exits 1 and leaves the marker; a clean rerun removes it", () => {
	const s = sandbox();
	try {
		s.addPatch("a-fails", `console.error("anchor drift"); process.exit(1);\n`);
		s.addPatch("b-passes", touches(join(s.dir, "b-ran")));
		let r = sh(APPLY, s.env);
		assert.equal(r.status, 1, r.stdout + r.stderr);
		assert.ok(existsSync(join(s.dir, "b-ran")), "the patch after the failing one still ran");
		assert.match(r.stderr, /ERROR: patch a-fails failed/);
		assert.match(r.stderr, /failed patches: a-fails/);
		assert.equal(readFileSync(s.marker, "utf8").trim(), "a-fails");
		// A release dir that is already partly patched: the passing patch is re-applied (idempotent) and the failure is reported again.
		r = sh(APPLY, s.env);
		assert.equal(r.status, 1); assert.equal(readFileSync(s.marker, "utf8").trim(), "a-fails");
		s.addPatch("a-fails", `process.exit(0);\n`);
		r = sh(APPLY, s.env);
		assert.equal(r.status, 0, r.stdout + r.stderr);
		assert.equal(existsSync(s.marker), false, "a fully clean run clears the marker");
	} finally { s.cleanup(); }
});

test("report script: silent without a marker, exit 1 with the failed names when the marker exists", () => {
	const s = sandbox();
	try {
		let r = sh(REPORT, s.env);
		assert.equal(r.status, 0); assert.equal(r.stderr, "");
		mkdirSync(dirname(s.marker), { recursive: true }); writeFileSync(s.marker, " btw-native-session prompt-start-race\n");
		r = sh(REPORT, s.env);
		assert.equal(r.status, 1);
		assert.match(r.stderr, /ERROR: Pi runtime patches are not all applied\. Failed:.*btw-native-session prompt-start-race/);
		assert.match(r.stderr, /mise run apply-pi-patches/);
	} finally { s.cleanup(); }
});

test("chezmoi chain: script 30 swallows the failure (exit 0, marker left), script 99 turns it into the apply's non-zero exit", { skip: spawnSync("chezmoi", ["--version"]).error ? "chezmoi not installed" : false }, () => {
	const s = sandbox();
	try {
		const cfg = join(s.dir, "chezmoi.yaml"); writeFileSync(cfg, "data:\n  profile: personal\n");
		const rendered = spawnSync("chezmoi", ["--source", ROOT, "--config", cfg, "--config-format", "yaml", "--destination", join(s.dir, "dest"), "execute-template"], { input: readFileSync(WRAPPER, "utf8"), encoding: "utf8", env: { PATH: process.env.PATH, HOME: s.dir } });
		assert.equal(rendered.status, 0, rendered.stderr);
		const script = join(s.dir, "30.sh"); writeFileSync(script, rendered.stdout);
		// The wrapper puts $HOME/.local/bin first on PATH, so the fake mise goes there.
		const bin = join(s.dir, ".local", "bin"); mkdirSync(bin, { recursive: true });
		const fakeMise = (code) => { writeFileSync(join(bin, "mise"), `#!/bin/sh\necho "fake mise: apply-pi-patches"\nexit ${code}\n`); chmodSync(join(bin, "mise"), 0o755); };
		const env = s.env;
		fakeMise(7);
		let r = sh(script, env);
		assert.equal(r.status, 0, "script 30 exits 0 so chezmoi runs the later scripts");
		assert.match(r.stderr, /ERROR: Pi patches failed \(exit 7\)/);
		assert.match(readFileSync(s.marker, "utf8"), /exited 7/);
		assert.equal(sh(REPORT, env).status, 1, "script 99 fails the apply");
		rmSync(s.marker); fakeMise(0);
		r = sh(script, env);
		assert.equal(r.status, 0); assert.equal(existsSync(s.marker), false);
		assert.equal(sh(REPORT, env).status, 0);
	} finally { s.cleanup(); }
});

test("wiring: script 99 is ignored on termux like script 30, and sorts after 90", () => {
	const ignore = readFileSync(join(ROOT, ".chezmoiignore"), "utf8");
	assert.ok(ignore.includes("99_report_pi_patch_failures.sh"));
	assert.ok(ignore.indexOf("99_report_pi_patch_failures.sh") < ignore.indexOf("{{- end }}", ignore.indexOf("30_apply_pi_patches.sh")));
});
