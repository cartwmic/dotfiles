// node --test tests/pi-patches/refresh_and_verify.test.mjs   (no Pi install, no network; temp dirs, fake `pi` and `chezmoi`)
// 1. apply_pi_patches.sh refreshes the Pi git extension the patches delegate to, and undoes the old helper's patch first when the checkout moves.
// 2. verify_dotfiles.sh passes after a clean apply and fails after a broken one.
import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { chmodSync, copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "../..");
const APPLY = join(ROOT, "dot_local/user_scripts/executable_apply_pi_patches.sh");
const VERIFY = join(ROOT, "dot_local/user_scripts/executable_verify_dotfiles.sh");
const SOURCE = "https://github.com/cartwmic/pi-response-visibility";
const git = (cwd, ...args) => spawnSync("git", ["-c", "user.email=t@t", "-c", "user.name=t", ...args], { cwd, encoding: "utf8" });
const run = (script, env) => spawnSync("/bin/sh", [script], { encoding: "utf8", env: { PATH: process.env.PATH, ...env } });
const exe = (file, body) => { writeFileSync(file, `#!/bin/sh\n${body}\n`); chmodSync(file, 0o755); };

function sandbox() {
	const dir = mkdtempSync(join(tmpdir(), "pi-refresh-verify-"));
	const patches = join(dir, "patches"), bin = join(dir, ".local", "bin"), agent = join(dir, "agent"), pi = join(dir, "pi-pkg"), log = join(dir, "log");
	mkdirSync(patches); mkdirSync(bin, { recursive: true }); mkdirSync(pi);
	copyFileSync(join(ROOT, "dot_local/share/pi-patches/pi-root.mjs"), join(patches, "pi-root.mjs"));
	writeFileSync(join(pi, "package.json"), JSON.stringify({ version: "1.2.0" }));
	const addPatch = (name, body) => { mkdirSync(join(patches, name), { recursive: true }); writeFileSync(join(patches, name, "patch.mjs"), body); };
	const env = { HOME: dir, PI_PATCHES_ROOT: patches, PI_PATCH_FAILURE_MARKER: join(dir, "failed"), PI_CODING_AGENT_DIR: agent, PI_ROOT: pi, PI_CHEZMOI_PROFILE: "personal", FAKE_LOG: log, PATH: `${bin}:${process.env.PATH}` };
	// A PATH with node and the system tools but no `pi` (node's own bin dir can hold a global pi).
	const nodeOnly = join(dir, "node-only"); mkdirSync(nodeOnly); symlinkSync(process.execPath, join(nodeOnly, "node"));
	return { nodeOnly, dir, patches, bin, agent, log, env, addPatch, cleanup: () => rmSync(dir, { recursive: true, force: true }) };
}
const lines = (s) => (existsSync(s.log) ? readFileSync(s.log, "utf8").trim().split("\n") : []);

// A fake response-visibility patch: logs which helper checkout it was given and with what argument.
const LOGGING_RV = `import { appendFileSync, readFileSync } from "node:fs";
const helper = process.env.PI_RESPONSE_VISIBILITY_HELPER;
appendFileSync(process.env.FAKE_LOG, "rv " + (process.argv[2] ?? "apply") + " helper=" + (helper ? readFileSync(helper, "utf8").trim() : "none") + "\\n");\n`;

function extensionCheckout(s) {
	const dir = join(s.agent, "git", "github.com", "cartwmic", "pi-response-visibility");
	mkdirSync(join(dir, "bin"), { recursive: true });
	git(dir, "init", "-q"); writeFileSync(join(dir, "bin", "core.mjs"), "old-helper\n"); git(dir, "add", "-A"); git(dir, "commit", "-qm", "old");
	writeFileSync(join(dir, "bin", "core.mjs"), "new-helper\n"); git(dir, "commit", "-qam", "new");
	git(dir, "checkout", "-q", "HEAD~1");
	return dir;
}

test("refresh: pi update --extension runs before the loop; when the helper checkout moves, the OLD helper rolls its patch back first, then the new one applies", () => {
	const s = sandbox();
	try {
		const dir = extensionCheckout(s);
		exe(join(s.bin, "pi"), `echo "pi $*" >> "$FAKE_LOG"; git -C "${dir}" checkout -q main 2>/dev/null || git -C "${dir}" checkout -q master`);
		s.addPatch("response-visibility", LOGGING_RV);
		const r = run(APPLY, { ...s.env, PI_PATCH_EXTENSIONS: SOURCE });
		assert.equal(r.status, 0, r.stdout + r.stderr);
		assert.deepEqual(lines(s), [`pi update --extension ${SOURCE}`, "rv --rollback helper=old-helper", "rv apply helper=none"]);
		assert.match(r.stdout, /response-visibility helper moved [0-9a-f]{7} -> [0-9a-f]{7}; rolling back its patch with the old helper first/);
	} finally { s.cleanup(); }
});

test("refresh: an unchanged checkout is not rolled back; a failed refresh is a WARN and the patches still run; an empty list never calls pi", () => {
	const s = sandbox();
	try {
		extensionCheckout(s);
		s.addPatch("response-visibility", LOGGING_RV);
		exe(join(s.bin, "pi"), `echo "pi $*" >> "$FAKE_LOG"`);
		let r = run(APPLY, { ...s.env, PI_PATCH_EXTENSIONS: SOURCE });
		assert.equal(r.status, 0); assert.deepEqual(lines(s), [`pi update --extension ${SOURCE}`, "rv apply helper=none"]);
		rmSync(s.log);
		exe(join(s.bin, "pi"), `echo "pi $*" >> "$FAKE_LOG"; exit 1`);
		r = run(APPLY, { ...s.env, PI_PATCH_EXTENSIONS: SOURCE });
		assert.equal(r.status, 0, "an offline refresh does not fail the apply");
		assert.match(r.stdout, /WARN: could not refresh .*pi-response-visibility; using the installed copy/);
		assert.deepEqual(lines(s), [`pi update --extension ${SOURCE}`, "rv apply helper=none"]);
		rmSync(s.log);
		r = run(APPLY, { ...s.env, PI_PATCH_EXTENSIONS: "" });
		assert.equal(r.status, 0); assert.deepEqual(lines(s), ["rv apply helper=none"]);
		rmSync(s.log);
		rmSync(join(s.bin, "pi"));
		r = run(APPLY, { ...s.env, PI_PATCH_EXTENSIONS: SOURCE, PATH: `${s.bin}:/usr/bin:/bin:${s.nodeOnly}` });
		assert.equal(r.status, 0); assert.match(r.stdout, /WARN: pi not on PATH/);
	} finally { s.cleanup(); }
});

test("verify: passes after a clean apply; fails on file drift, on a recorded patch failure, and on a patch that no longer verifies", () => {
	const s = sandbox();
	try {
		exe(join(s.bin, "chezmoi"), `[ "$1 $2" = "verify --exclude=scripts" ] || exit 2; [ -z "$FAKE_VERIFY_FAIL" ] || { echo "drift: .zshrc"; exit 1; }`);
		s.addPatch("good", `process.exit(process.argv.includes("--check") ? 0 : 2);\n`);
		let r = run(VERIFY, s.env);
		assert.equal(r.status, 0, r.stdout + r.stderr); assert.match(r.stdout, /PASS/); assert.match(r.stdout, /ok: Pi patch good/);
		r = run(VERIFY, { ...s.env, FAKE_VERIFY_FAIL: "1" });
		assert.equal(r.status, 1); assert.match(r.stderr, /FAIL: managed files differ from the source/); assert.match(r.stderr, /drift: \.zshrc/);
		writeFileSync(s.env.PI_PATCH_FAILURE_MARKER, " response-visibility\n");
		r = run(VERIFY, s.env);
		assert.equal(r.status, 1); assert.match(r.stderr, /FAIL: Pi patch failure recorded: response-visibility/);
		rmSync(s.env.PI_PATCH_FAILURE_MARKER);
		s.addPatch("bad", `console.error("anchor drift"); process.exit(1);\n`);
		r = run(VERIFY, s.env);
		assert.equal(r.status, 1); assert.match(r.stderr, /FAIL: Pi patch bad does not verify/); assert.match(r.stdout, /ok: Pi patch good/);
		assert.match(r.stderr, /FAILED: this machine does not match/);
	} finally { s.cleanup(); }
});

test("verify: with Pi absent the Pi patches are not checked, and the files check alone decides", () => {
	const s = sandbox();
	try {
		exe(join(s.bin, "chezmoi"), `exit 0`);
		exe(join(s.bin, "npm"), `exit 1`); // no global npm root either: Pi is not found anywhere
		s.addPatch("bad", `process.exit(1);\n`);
		const env = { ...s.env, PI_ROOT: "", PI_CODING_AGENT_DIR: join(s.dir, "none"), PATH: `${s.bin}:/usr/bin:/bin:${s.nodeOnly}` };
		const r = run(VERIFY, env);
		assert.equal(r.status, 0, r.stdout + r.stderr); assert.match(r.stdout, /Pi is not installed/);
	} finally { s.cleanup(); }
});

test("verify: checks the patches in the chezmoi source, so an orphan of a retired patch in the deployed directory cannot fail a clean machine", () => {
	const s = sandbox();
	try {
		const source = join(s.dir, "src"), sourcePatches = join(source, "dot_local", "share", "pi-patches"), deployed = join(s.dir, ".local", "share", "pi-patches");
		mkdirSync(sourcePatches, { recursive: true }); mkdirSync(join(deployed, "openai-codex-gpt-6-astra"), { recursive: true });
		copyFileSync(join(ROOT, "dot_local/share/pi-patches/pi-root.mjs"), join(sourcePatches, "pi-root.mjs"));
		copyFileSync(join(ROOT, "dot_local/share/pi-patches/pi-root.mjs"), join(deployed, "pi-root.mjs"));
		mkdirSync(join(sourcePatches, "good"), { recursive: true }); writeFileSync(join(sourcePatches, "good", "patch.mjs"), "process.exit(0);\n");
		writeFileSync(join(deployed, "openai-codex-gpt-6-astra", "patch.mjs"), `console.error("pi openai-codex catalog not installed; cannot verify patch"); process.exit(1);\n`);
		exe(join(s.bin, "chezmoi"), `[ "$1" = "source-path" ] && { echo "${source}"; exit 0; }; exit 0`);
		const env = { ...s.env }; delete env.PI_PATCHES_ROOT;
		const r = run(VERIFY, env);
		assert.equal(r.status, 0, r.stdout + r.stderr); assert.match(r.stdout, /ok: Pi patch good/); assert.doesNotMatch(r.stdout + r.stderr, /astra/);
	} finally { s.cleanup(); }
});

test(".chezmoiremove: the retired openai-codex-gpt-6-astra patch directory is removed on every profile", () => {
	const text = readFileSync(join(ROOT, ".chezmoiremove"), "utf8");
	const index = text.indexOf(".local/share/pi-patches/openai-codex-gpt-6-astra");
	assert.ok(index > 0);
	// Not inside a profile-gated block: every `{{ if` before it has been closed by an `{{ end`.
	const before = text.slice(0, index);
	assert.equal((before.match(/\{\{-? *if /g) ?? []).length, (before.match(/\{\{-? *end/g) ?? []).length);
});
