// Version-aware entry point for runtime patches whose anchors differ between Pi minor versions.
// Not a patch: the apply loop only runs */patch.mjs, and those files call dispatchByPiVersion().
//
// A patch directory keeps one payload per Pi minor series where anchors changed (patch.pi-1.1.mjs, patch.pi-1.2.mjs).
// A payload is named for the first series it supports and serves every later series until a newer payload exists.
// A variants key may also be a full version ("1.5.1") when anchors changed inside a minor series; that payload
// serves that version and every later one until a newer payload exists.
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

// Floor keys are "major.minor" or "major.minor.patch" (patch defaults to 0); compared newest first.
const floorParts = (key) => { const [major, minor, patch = 0] = key.split(".").map(Number); return [major, minor, patch]; };
const newestFirst = (a, b) => {
	const [am, an, ap] = floorParts(a), [bm, bn, bp] = floorParts(b);
	return bm - am || bn - an || bp - ap;
};
const versionParts = (version) => { const m = SERIES.exec(String(version).trim()); return `${m[1]}.${m[2]}.${m[3]}`; };

/** Pure selection, exported for tests. root === undefined means "Pi not installed". */
export function selectPayload(root, variants, readVersion = (r) => JSON.parse(readFileSync(join(r, "package.json"), "utf8")).version) {
	const supported = Object.keys(variants).sort(newestFirst);
	if (!root) return { kind: "not-installed", series: supported[0], file: variants[supported[0]], supported };
	let version;
	try { version = readVersion(root); } catch (error) { return { kind: "unreadable", error: String(error?.message ?? error), supported }; }
	const series = seriesOf(version);
	if (!series) return { kind: "unparseable", version, supported };
	const floor = supported.find((s) => newestFirst(s, versionParts(version)) >= 0);
	if (!floor) return { kind: "unsupported", version, supported };
	return { kind: "match", version, series: floor, file: variants[floor], supported };
}

export function dispatchByPiVersion(metaUrl, { name, packageEnv, variants }) {
	const dir = dirname(fileURLToPath(metaUrl));
	const log = (m) => console.log(`[pi-patch:${name}] ${m}`);
	const root = (packageEnv && process.env[packageEnv]) || piCodingAgentRoot();
	const pick = selectPayload(root, variants);
	const list = pick.supported.map((s) => (s.split(".").length > 2 ? `${s}+` : `${s}.x`)).join(", ");
	if (pick.kind === "unreadable") { console.error(`[pi-patch:${name}] ERROR: cannot read Pi version from ${root}/package.json (${pick.error}); supported Pi series: ${list}; no files were changed`); process.exit(1); }
	if (pick.kind === "unparseable") { console.error(`[pi-patch:${name}] ERROR: unrecognised Pi version "${pick.version}"; supported Pi series: ${list}; no files were changed`); process.exit(1); }
	if (pick.kind === "unsupported") { console.error(`[pi-patch:${name}] ERROR: no payload for Pi ${pick.version}; payloads start at Pi ${pick.supported.at(-1)}.x (${list}). No files were changed`); process.exit(1); }
	const file = join(dir, pick.file);
	if (!existsSync(file)) { console.error(`[pi-patch:${name}] ERROR: payload ${pick.file} is missing from ${dir}; no files were changed`); process.exit(1); }
	// Pi not installed: the payload prints its own one-line skip (or cannot-verify) notice, so the dispatcher stays quiet.
	if (pick.kind === "match") log(`Pi ${pick.version} -> payload ${pick.file}`);
	const run = spawnSync(process.execPath, [file, ...process.argv.slice(2)], { stdio: "inherit", env: process.env });
	if (run.error) { console.error(`[pi-patch:${name}] ERROR: could not run ${pick.file}: ${run.error.message}`); process.exit(1); }
	process.exit(run.status ?? (run.signal ? 1 : 0));
}
