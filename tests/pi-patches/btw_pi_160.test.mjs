// node --test tests/pi-patches/btw_pi_160.test.mjs
// btw-native-session against the real, published Pi 1.6.0 package (the one anchor set the other tests cannot fake).
// Needs the network and npm: it installs @earendil-works/pi-coding-agent@1.6.0 into a temp dir, then copies the tree before each patch run.
// A failed install fails the test; it is not skipped, so CI cannot pass without the real package.
import test, { before, after } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { cpSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "../..");
const PATCH = join(ROOT, "dot_local/share/pi-patches/btw-native-session/patch.mjs");
const PI_VERSION = "1.6.0";

let work, pristine;

before(() => {
	work = mkdtempSync(join(tmpdir(), "btw-pi-160-"));
	const r = spawnSync("npm", ["install", "--ignore-scripts", "--no-audit", "--no-fund", "--prefix", work, `@earendil-works/pi-coding-agent@${PI_VERSION}`], { encoding: "utf8" });
	assert.equal(r.status, 0, `npm install failed:\n${r.stdout}${r.stderr}`);
	pristine = join(work, "node_modules/@earendil-works");
	const version = JSON.parse(readFileSync(join(pristine, "pi-coding-agent/package.json"), "utf8")).version;
	assert.equal(version, PI_VERSION);
});
after(() => rmSync(work, { recursive: true, force: true }));

const files = (dir) => readdirSync(dir, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? files(join(dir, e.name)) : [join(dir, e.name)]));
const tree = (dir) => Object.fromEntries(files(dir).map((f) => [relative(dir, f), createHash("sha256").update(readFileSync(f)).digest("hex")]));

// Patches a private copy; the pristine install is never written. Only the @earendil-works scope is copied (the patch reads nothing else).
function copy() {
	const dir = mkdtempSync(join(tmpdir(), "btw-pi-160-copy-"));
	const scope = join(dir, "node_modules/@earendil-works");
	cpSync(pristine, scope, { recursive: true });
	const run = (profile, ...args) => spawnSync(process.execPath, [PATCH, ...args], {
		encoding: "utf8", env: { PATH: dirname(process.execPath), HOME: dir, PI_ROOT: join(scope, "pi-coding-agent"), PI_CHEZMOI_PROFILE: profile },
	});
	return { dir, scope, run };
}

test("Pi 1.6.0: apply patches the real anchors, is idempotent, and rollback restores the pristine tree", () => {
	const s = copy();
	try {
		const original = tree(s.scope);
		const check = s.run("personal", "--check");
		assert.equal(check.status, 0, check.stdout + check.stderr);
		assert.match(check.stdout, /payload patch\.pi-1\.6\.0\.mjs/, "the dispatcher picks the 1.6.0 payload");
		assert.ok(JSON.parse(check.stdout.trim().split("\n").at(-1)).pendingFiles > 0, "--check sees work to do");
		assert.deepEqual(tree(s.scope), original, "--check writes nothing");

		const applied = s.run("personal");
		assert.equal(applied.status, 0, applied.stdout + applied.stderr);
		const patched = tree(s.scope);
		const changed = Object.keys(patched).filter((f) => patched[f] !== original[f]);
		assert.ok(changed.length >= 10, `many files changed, got ${changed.length}`);

		const again = s.run("personal");
		assert.equal(again.status, 0, again.stdout + again.stderr);
		assert.equal(JSON.parse(again.stdout.trim().split("\n").at(-1)).pendingFiles, 0, "second apply has nothing pending");
		assert.deepEqual(tree(s.scope), patched, "second apply changes nothing");

		const back = s.run("personal", "--rollback");
		assert.equal(back.status, 0, back.stdout + back.stderr);
		assert.deepEqual(tree(s.scope), original, "rollback restores the pristine tree byte for byte");
	} finally { rmSync(s.dir, { recursive: true, force: true }); }
});

test("Pi 1.6.0: the work profile applies the same payload", () => {
	const s = copy();
	try {
		const original = tree(s.scope);
		const r = s.run("axon-work-computer");
		assert.equal(r.status, 0, r.stdout + r.stderr);
		assert.notDeepEqual(tree(s.scope), original, "work profile patched the tree");
	} finally { rmSync(s.dir, { recursive: true, force: true }); }
});

test("Pi 1.6.0: one drifted anchor fails loudly and writes nothing", () => {
	const s = copy();
	try {
		const chunks = join(s.scope, "pi-coding-agent/dist/bundle/chunks");
		const edits = JSON.parse(readFileSync(join(dirname(PATCH), "edits.pi-1.6.0.json"), "utf8"));
		const edit = edits.find((e) => e.path.startsWith("dist/bundle/chunks/") && e.old.length > 40);
		const chunk = readdirSync(chunks).find((n) => n.endsWith(".js") && readFileSync(join(chunks, n), "utf8").includes(edit.old));
		assert.ok(chunk, "the anchor is in a bundle chunk of the real Pi 1.6.0");
		const file = join(chunks, chunk);
		writeFileSync(file, readFileSync(file, "utf8").replace(edit.old, () => edit.old.slice(0, -3) + "XXX"));
		const drifted = tree(s.scope);
		const r = s.run("personal");
		assert.equal(r.status, 1, r.stdout + r.stderr);
		assert.match(r.stderr, /anchor drift|no files were changed/);
		assert.deepEqual(tree(s.scope), drifted, "nothing was written");
	} finally { rmSync(s.dir, { recursive: true, force: true }); }
});
