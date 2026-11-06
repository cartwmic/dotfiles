// node --test tests/pi-patches/apply_no_pi.test.mjs   (no Pi install, no network; throwaway HOME and temp dirs only)
// Runs the real apply script with Pi absent: an empty agent dir, no PI_ROOT, no `pi` on PATH, and a fake `npm`
// whose `npm root -g` names an empty global root. Pi-installed behaviour is in apply_pi_installed.test.mjs.
import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "../..");
const PATCHES = join(ROOT, "dot_local/share/pi-patches");
const SCRIPT = join(ROOT, "dot_local/user_scripts/executable_apply_pi_patches.sh");
// Pinned, not derived from the directory: a patch that goes missing from the loop must fail here, and a new one must be added on purpose.
const NAMES = ["anthropic-idle-watchdog", "ask-user-question-render", "btw-native-session", "cursor-provider", "custom-message-marker", "empty-turn-retry",
	"headless-extension-drain", "prompt-start-race", "response-visibility", "settlement-abort", "standing-reminder-origin"];

function files(dir) {
	return readdirSync(dir, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? files(join(dir, e.name)) : [join(dir, e.name)]));
}

function sandbox() {
	const dir = mkdtempSync(join(tmpdir(), "pi-apply-nopi-"));
	const home = join(dir, "home"), agent = join(dir, "agent"), bin = join(dir, "bin");
	for (const d of [home, agent, bin]) mkdirSync(d);
	const globalRoot = join(dir, "empty-global", "lib", "node_modules");
	writeFileSync(join(bin, "npm"), `#!/bin/sh\nif [ "$1" = root ] && [ "$2" = -g ]; then echo "${globalRoot}"; exit 0; fi\necho "fake npm: unexpected $*" >&2; exit 2\n`);
	chmodSync(join(bin, "npm"), 0o755);
	// Explicit env, not process.env: nothing from the developer's shell (PI_ROOT, HOME, a real pi on PATH) can leak in.
	const env = { HOME: home, PATH: [bin, dirname(process.execPath), "/usr/bin", "/bin"].join(":"), PI_CODING_AGENT_DIR: agent, PI_PATCHES_ROOT: PATCHES };
	return { dir, home, env, cleanup: () => rmSync(dir, { recursive: true, force: true }) };
}

for (const profile of ["personal", "axon-work-computer"]) {
	test(`apply with Pi absent (${profile}): exit 0, one skip notice per patch, nothing written under HOME`, () => {
		const s = sandbox();
		try {
			const r = spawnSync("/bin/sh", [SCRIPT], { encoding: "utf8", env: { ...s.env, PI_CHEZMOI_PROFILE: profile } });
			assert.equal(r.status, 0, `exit ${r.status}\n${r.stdout}${r.stderr}`);
			assert.equal(r.stderr, "");
			const lines = r.stdout.split("\n").filter((l) => l && !l.startsWith("[apply_pi_patches] applying patch: "));
			assert.equal(lines.length, NAMES.length, `one notice per patch (${NAMES.length}), got:\n${lines.join("\n")}`);
			for (const name of NAMES) assert.ok(existsSync(join(PATCHES, name, "patch.mjs")), `${name} is a patch directory`);
			for (const name of NAMES) {
				const hits = lines.filter((l) => l.startsWith(`[pi-patch:${name}] `) || l.startsWith(`[${name}] `));
				assert.equal(hits.length, 1, `${name}: exactly one notice, got ${hits.length}`);
				assert.match(hits[0], /not installed|skipped|nothing to patch/, name);
			}
			assert.doesNotMatch(r.stdout, /ERROR/);
			assert.deepEqual(files(s.home), [], "no file written under the throwaway HOME");
		} finally { s.cleanup(); }
	});
}

test("check with Pi absent: btw-native-session and response-visibility cannot verify (exit 1), no silent skip", () => {
	const s = sandbox();
	try {
		for (const name of ["btw-native-session", "response-visibility"]) {
			const r = spawnSync(process.execPath, [join(PATCHES, name, "patch.mjs"), "--check"], { encoding: "utf8", env: { ...s.env, PI_CHEZMOI_PROFILE: "personal" } });
			assert.equal(r.status, 1, name);
			assert.match(r.stdout + r.stderr, /Pi is not installed; cannot verify/, name);
		}
		assert.deepEqual(files(s.home), [], "no file written under the throwaway HOME");
	} finally { s.cleanup(); }
});

test("Pi present but unpatchable still fails loudly: btw-native-session and response-visibility exit 1, neither skips", () => {
	const s = sandbox();
	try {
		const pi = join(s.dir, "pi-coding-agent");
		mkdirSync(pi);
		writeFileSync(join(pi, "package.json"), JSON.stringify({ name: "@earendil-works/pi-coding-agent", version: "1.5.0" }));
		const env = { ...s.env, PI_CHEZMOI_PROFILE: "personal", PI_ROOT: pi };
		let r = spawnSync(process.execPath, [join(PATCHES, "btw-native-session/patch.mjs")], { encoding: "utf8", env });
		assert.equal(r.status, 1, "btw-native-session: no bundle chunks means no patch");
		assert.doesNotMatch(r.stdout, /skipped/);
		r = spawnSync(process.execPath, [join(PATCHES, "response-visibility/patch.mjs")], { encoding: "utf8", env });
		assert.equal(r.status, 1, "response-visibility: no helper means no patch");
		assert.match(r.stderr, /missing canonical helper/);
		assert.doesNotMatch(r.stdout, /skipped/);
	} finally { s.cleanup(); }
});
