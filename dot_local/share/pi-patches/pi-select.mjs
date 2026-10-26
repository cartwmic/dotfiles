// Version-aware entry point for runtime patches whose anchors differ between Pi minor versions.
// Not a patch: the apply loop only runs */patch.mjs, and those files call dispatchByPiVersion().
//
// A patch directory keeps one payload per Pi minor series where anchors changed (patch.pi-1.1.mjs, patch.pi-1.2.mjs).
// A payload is named for the first series it supports and serves every later series until a newer payload exists.
// patch.mjs stays the single entry point the apply loop, the onchange hash and the proofs already use.
//
// Selection is by version floor; whether a payload fits is decided by its own checked anchors, which fail
// with no writes on drift. Rules (fail loudly, never silently skip):
//   - Pi installed -> run the newest payload whose series is <= the installed series, with the same argv/env/stdio, and return its exit code.
//   - Pi installed, version unparseable or older than every payload -> print what is supported and exit 1; no file is touched.
//   - Pi not installed -> run the NEWEST payload, which already owns the "not installed; skipped" (or "cannot verify" with --check) behaviour.
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { piCodingAgentRoot } from "./pi-root.mjs";

const SERIES = /^(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?$/;

export function seriesOf(version) {
	const m = SERIES.exec(String(version ?? "").trim());
	return m ? `${m[1]}.${m[2]}` : undefined;
}

const newestFirst = (a, b) => {
	const [am, an] = a.split(".").map(Number), [bm, bn] = b.split(".").map(Number);
	return bm - am || bn - an;
};

/** Pure selection, exported for tests. root === undefined means "Pi not installed". */
export function selectPayload(root, variants, readVersion = (r) => JSON.parse(readFileSync(join(r, "package.json"), "utf8")).version) {
	const supported = Object.keys(variants).sort(newestFirst);
	if (!root) return { kind: "not-installed", series: supported[0], file: variants[supported[0]], supported };
	let version;
	try { version = readVersion(root); } catch (error) { return { kind: "unreadable", error: String(error?.message ?? error), supported }; }
	const series = seriesOf(version);
	if (!series) return { kind: "unparseable", version, supported };
	const floor = supported.find((s) => newestFirst(s, series) >= 0);
	if (!floor) return { kind: "unsupported", version, supported };
	return { kind: "match", version, series: floor, file: variants[floor], supported };
}

export function dispatchByPiVersion(metaUrl, { name, packageEnv, variants }) {
	const dir = dirname(fileURLToPath(metaUrl));
	const log = (m) => console.log(`[pi-patch:${name}] ${m}`);
	const root = (packageEnv && process.env[packageEnv]) || piCodingAgentRoot();
	const pick = selectPayload(root, variants);
	const list = pick.supported.map((s) => `${s}.x`).join(", ");
	if (pick.kind === "unreadable") { console.error(`[pi-patch:${name}] ERROR: cannot read Pi version from ${root}/package.json (${pick.error}); supported Pi series: ${list}; no files were changed`); process.exit(1); }
	if (pick.kind === "unparseable") { console.error(`[pi-patch:${name}] ERROR: unrecognised Pi version "${pick.version}"; supported Pi series: ${list}; no files were changed`); process.exit(1); }
	if (pick.kind === "unsupported") { console.error(`[pi-patch:${name}] ERROR: no payload for Pi ${pick.version}; payloads start at Pi ${pick.supported.at(-1)}.x (${list}). No files were changed`); process.exit(1); }
	const file = join(dir, pick.file);
	if (!existsSync(file)) { console.error(`[pi-patch:${name}] ERROR: payload ${pick.file} is missing from ${dir}; no files were changed`); process.exit(1); }
	log(pick.kind === "match" ? `Pi ${pick.version} -> payload ${pick.file}` : `Pi not installed -> ${pick.file} decides (skip or cannot-verify)`);
	const run = spawnSync(process.execPath, [file, ...process.argv.slice(2)], { stdio: "inherit", env: process.env });
	if (run.error) { console.error(`[pi-patch:${name}] ERROR: could not run ${pick.file}: ${run.error.message}`); process.exit(1); }
	process.exit(run.status ?? (run.signal ? 1 : 0));
}
