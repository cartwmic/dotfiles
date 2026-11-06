// node --test tests/pi-patches/apply_pi_installed.test.mjs
// Pi-installed path against a pristine Pi 1.5.0. Needs the network-installed package and a response-visibility helper
// that matches Pi 1.5.0, so it is skipped unless both are given (CI does not run it):
//   npm install --ignore-scripts --prefix <dir> @earendil-works/pi-coding-agent@1.5.0
//   PI_1_5_NODE_MODULES=<dir>/node_modules
//   PI_RESPONSE_VISIBILITY_HELPER=<absolute bin/core.mjs of cartwmic/pi-response-visibility at f1f74eb or later>
// The package is copied to a temp dir before patching; the pristine install is never written.
import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { cpSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "../..");
const PATCHES = join(ROOT, "dot_local/share/pi-patches");
const SCRIPT = join(ROOT, "dot_local/user_scripts/executable_apply_pi_patches.sh");
const PRISTINE = process.env.PI_1_5_NODE_MODULES;
const HELPER = process.env.PI_RESPONSE_VISIBILITY_HELPER;
const SKIP = PRISTINE && HELPER ? false : "set PI_1_5_NODE_MODULES and PI_RESPONSE_VISIBILITY_HELPER (see header)";

function files(dir) {
	return readdirSync(dir, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? files(join(dir, e.name)) : [join(dir, e.name)]));
}

function tree(dir) {
	const out = {};
	for (const f of files(dir)) out[relative(dir, f)] = createHash("sha256").update(readFileSync(f)).digest("hex");
	return out;
}

// Only the @earendil-works scope is copied (pi-coding-agent and its hoisted pi-ai); the patches never read the rest.
function sandbox() {
	const dir = mkdtempSync(join(tmpdir(), "pi-apply-installed-"));
	const scope = join(dir, "node_modules", "@earendil-works");
	cpSync(join(PRISTINE, "@earendil-works"), scope, { recursive: true });
	const home = join(dir, "home"), agent = join(dir, "agent");
	mkdirSync(home); mkdirSync(agent);
	const env = {
		HOME: home, PATH: [dirname(process.execPath), "/usr/bin", "/bin"].join(":"), PI_CODING_AGENT_DIR: agent, PI_PATCHES_ROOT: PATCHES,
		PI_ROOT: join(scope, "pi-coding-agent"), PI_CHEZMOI_PROFILE: "personal", PI_RESPONSE_VISIBILITY_HELPER: HELPER,
	};
	return { dir, scope, env, cleanup: () => rmSync(dir, { recursive: true, force: true }) };
}

const apply = (env) => spawnSync("/bin/sh", [SCRIPT], { encoding: "utf8", env });

test("Pi 1.5.0 installed: apply exits 0, a second apply exits 0 and changes nothing", { skip: SKIP }, () => {
	const s = sandbox();
	try {
		const first = apply(s.env);
		assert.equal(first.status, 0, first.stdout + first.stderr);
		assert.doesNotMatch(first.stdout + first.stderr, /ERROR/);
		// With Pi installed the loop still names each patch before it runs.
		assert.equal(first.stdout.split("\n").filter((l) => l.startsWith("[apply_pi_patches] applying patch: ")).length, 11);
		const afterFirst = tree(s.scope);
		const second = apply(s.env);
		assert.equal(second.status, 0, second.stdout + second.stderr);
		assert.deepEqual(tree(s.scope), afterFirst, "second apply is a no-op on the Pi tree");
	} finally { s.cleanup(); }
});

test("Pi 1.5.0 installed, one anchor drifted: apply exits 1 and names the patch", { skip: SKIP }, () => {
	const s = sandbox();
	try {
		const edits = JSON.parse(readFileSync(join(PATCHES, "btw-native-session/edits.pi-1.5.json"), "utf8"));
		const edit = edits.find((e) => e.package === "pi-coding-agent" && e.old.length > 40);
		const chunks = join(s.scope, "pi-coding-agent/dist/bundle/chunks");
		const chunk = readdirSync(chunks).find((n) => n.endsWith(".js") && readFileSync(join(chunks, n), "utf8").includes(edit.old));
		assert.ok(chunk, "the anchor is in a bundle chunk of the pristine Pi");
		writeFileSync(join(chunks, chunk), readFileSync(join(chunks, chunk), "utf8").replace(edit.old, edit.old.slice(0, -3) + "XXX"));
		const r = apply(s.env);
		assert.equal(r.status, 1, r.stdout + r.stderr);
		// log_error writes to stderr; the loop's ERROR line is there, not on stdout.
		assert.match(r.stderr, /ERROR: patch btw-native-session failed/);
	} finally { s.cleanup(); }
});
