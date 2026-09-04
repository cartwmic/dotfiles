#!/usr/bin/env node
// chezmoi-pi-patch:openai-codex-gpt-6-astra
//
// Idempotently inserts gpt-6-astra into:
//   1. the CLI-load-bearing inlined catalog in pi-coding-agent's bundle
//      (dist/bundle/chunks/*openai_codex_default*) — this is what
//      `pi --list-models` reads
//   2. pi-ai's openai-codex.json (SDK / unbundled imports)
//
// JSON cannot carry a // marker. The bundle insert includes MARKER so
// pi-patch-guard can watch the CLI file. State `target` is the bundle.
// State `catalogStopgap` lets the guard warn at session start when the
// unpatched catalog already ships the id (delete this patch).
//
// PROFILE GATE: personal only (same as hide-nonbridge-claude-models).
// Delete this patch once an unpatched catalog already ships gpt-6-astra.
//
// Usage:
//   node patch.mjs [--check]
//   PI_CHEZMOI_PROFILE=personal node patch.mjs

import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { homedir } from "node:os";

const PATCH_REVISION = 3;
const PATCH_NAME = "openai-codex-gpt-6-astra";
const MODEL_ID = "gpt-6-astra";
const CATALOG_GROUP = "openai-codex-responses";
const MARKER_PREFIX = `chezmoi-pi-patch:${PATCH_NAME}`;
const MARKER = `${MARKER_PREFIX} v${PATCH_REVISION}`;
const MARKER_COMMENT = `/*${MARKER}*/`;
const BACKUP_SUFFIX = ".orig.chezmoi-pi-patch";
const STATE_DIR = join(homedir(), ".local", "state", "chezmoi-pi-patches");
const STATE_FILE = join(STATE_DIR, `${PATCH_NAME}.json`);
const CHEZMOI_SOURCE = `dot_local/share/pi-patches/${PATCH_NAME}`;
const CATALOG_STOPGAP = { provider: "openai-codex", id: MODEL_ID };

const BUNDLE_ASSIGN =
	'var OPENAI_CODEX_MODELS=flattenModelCatalog("openai-codex",openai_codex_default);';
const BUNDLE_DECL = "var openai_codex_default=";
const BUNDLE_ENTRY = `"${MODEL_ID}":{id:"${MODEL_ID}",name:"GPT-6 Astra",api:"openai-codex-responses",provider:"openai-codex",baseUrl:"https://chatgpt.com/backend-api",reasoning:!0,input:["text","image"],cost:{input:10,output:50,cacheRead:1,cacheWrite:12.5,tiers:[{inputTokensAbove:272e3,input:20,output:75,cacheRead:2,cacheWrite:25}]},contextWindow:872e3,maxTokens:128e3,thinkingLevelMap:{xhigh:"xhigh",max:"max",minimal:"low"},compat:{supportsOpenAIGrammarTools:!0,supportsAdditionalTools:!0,supportsToolSearch:!0}}`;
const BUNDLE_INSERT = `,${MARKER_COMMENT}${BUNDLE_ENTRY}`;
// Upgrade only our exact v2 insert; never rewrite an upstream model entry.
const V2_INSERT = BUNDLE_INSERT.replace(`${MARKER_PREFIX} v3`, `${MARKER_PREFIX} v2`)
	.replace("contextWindow:872e3", "contextWindow:272e3");

const MODEL = {
	id: MODEL_ID,
	name: "GPT-6 Astra",
	api: "openai-codex-responses",
	provider: "openai-codex",
	baseUrl: "https://chatgpt.com/backend-api",
	reasoning: true,
	input: ["text", "image"],
	cost: {
		input: 10,
		output: 50,
		cacheRead: 1,
		cacheWrite: 12.5,
		tiers: [
			{
				inputTokensAbove: 272000,
				input: 20,
				output: 75,
				cacheRead: 2,
				cacheWrite: 25,
			},
		],
	},
	contextWindow: 872000,
	maxTokens: 128000,
	thinkingLevelMap: { xhigh: "xhigh", max: "max", minimal: "low" },
	compat: {
		supportsOpenAIGrammarTools: true,
		supportsAdditionalTools: true,
		supportsToolSearch: true,
	},
};

const log = (msg) => console.log(`[pi-patch:${PATCH_NAME}] ${msg}`);
const fail = (msg) => {
	console.error(`[pi-patch:${PATCH_NAME}] ERROR: ${msg}`);
	process.exit(1);
};

const checkOnly = process.argv.includes("--check");
const profile = process.env.PI_CHEZMOI_PROFILE ?? "";
const wantPatched = profile === "personal";

const SCOPES = ["@earendil-works", "@mariozechner"];
const JSON_SUBPATH = "dist/providers/data/openai-codex.json";

function firstExisting(paths) {
	for (const p of paths) {
		if (p && existsSync(p)) return p;
	}
	return null;
}

function npmRoot() {
	try {
		return execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim();
	} catch {
		return null;
	}
}

function pcaPackageDirs() {
	const dirs = [];
	const requireFromHome = createRequire(join(homedir(), "package.json"));
	for (const scope of SCOPES) {
		try {
			dirs.push(dirname(requireFromHome.resolve(`${scope}/pi-coding-agent/package.json`)));
		} catch {
			/* not resolvable from $HOME */
		}
	}
	const root = npmRoot();
	if (root) {
		for (const scope of SCOPES) {
			dirs.push(join(root, scope, "pi-coding-agent"));
		}
	}
	return dirs.filter((d, i, all) => all.indexOf(d) === i && existsSync(join(d, "package.json")));
}

function locateJsonTarget() {
	const requireFromHome = createRequire(join(homedir(), "package.json"));
	const candidates = [];
	for (const scope of SCOPES) {
		try {
			candidates.push(requireFromHome.resolve(`${scope}/pi-ai/${JSON_SUBPATH}`));
		} catch {
			/* not hoisted */
		}
		try {
			const pcaPkg = requireFromHome.resolve(`${scope}/pi-coding-agent/package.json`);
			candidates.push(join(dirname(pcaPkg), "node_modules", scope, "pi-ai", JSON_SUBPATH));
		} catch {
			/* pi-coding-agent not under this scope */
		}
	}
	const root = npmRoot();
	if (root) {
		for (const scope of SCOPES) {
			candidates.push(join(root, scope, "pi-coding-agent", "node_modules", scope, "pi-ai", JSON_SUBPATH));
			candidates.push(join(root, scope, "pi-ai", JSON_SUBPATH));
		}
	}
	return firstExisting(candidates);
}

function locateBundleTarget() {
	for (const pca of pcaPackageDirs()) {
		const chunks = join(pca, "dist", "bundle", "chunks");
		if (!existsSync(chunks)) continue;
		const hits = [];
		for (const name of readdirSync(chunks)) {
			if (!name.endsWith(".js")) continue;
			const path = join(chunks, name);
			const text = readFileSync(path, "utf8");
			if (text.includes(BUNDLE_ASSIGN) && text.includes(BUNDLE_DECL)) hits.push(path);
		}
		if (hits.length === 1) return hits[0];
		if (hits.length > 1) fail(`multiple bundle chunks contain openai_codex_default: ${hits.join(", ")}`);
	}
	return null;
}

function getInstalledVersions() {
	const versions = { piCodingAgent: null, piAi: null, scope: null };
	for (const pca of pcaPackageDirs()) {
		try {
			versions.piCodingAgent = JSON.parse(readFileSync(join(pca, "package.json"), "utf8")).version;
			versions.scope = pca.includes("@mariozechner") ? "@mariozechner" : "@earendil-works";
		} catch {
			/* missing */
		}
		for (const scope of SCOPES) {
			const nested = join(pca, "node_modules", scope, "pi-ai", "package.json");
			if (existsSync(nested)) {
				versions.piAi = JSON.parse(readFileSync(nested, "utf8")).version;
				break;
			}
		}
		if (versions.piCodingAgent) break;
	}
	return versions;
}

const sha256 = (s) => createHash("sha256").update(s).digest("hex");

function writeStateFile(payload) {
	try {
		mkdirSync(STATE_DIR, { recursive: true });
		writeFileSync(
			STATE_FILE,
			JSON.stringify(
				{
					...payload,
					patchName: PATCH_NAME,
					marker: MARKER,
					when: new Date().toISOString(),
				},
				null,
				2,
			),
		);
	} catch {
		/* best-effort */
	}
}

function stopgapState(extra) {
	return {
		catalogStopgap: CATALOG_STOPGAP,
		chezmoiSource: CHEZMOI_SOURCE,
		...extra,
	};
}

function parseCatalog(raw, pathForError) {
	let data;
	try {
		data = JSON.parse(raw);
	} catch (err) {
		fail(`invalid JSON in ${pathForError}: ${err.message}`);
	}
	const group = data?.[CATALOG_GROUP];
	if (!group || typeof group !== "object" || Array.isArray(group)) {
		fail(`${pathForError} has no ${CATALOG_GROUP} object`);
	}
	return { data, group };
}

function jsonHasAstra(raw, pathForError) {
	return Object.prototype.hasOwnProperty.call(parseCatalog(raw, pathForError).group, MODEL_ID);
}

function catalogSlice(source, pathForError) {
	const assignAt = source.indexOf(BUNDLE_ASSIGN);
	if (assignAt < 0) fail(`${pathForError} has no ${BUNDLE_ASSIGN}`);
	if (source.indexOf(BUNDLE_ASSIGN, assignAt + 1) >= 0) {
		fail(`${pathForError} has multiple OPENAI_CODEX_MODELS assignments`);
	}
	const declAt = source.lastIndexOf(BUNDLE_DECL, assignAt);
	if (declAt < 0) fail(`${pathForError} has no openai_codex_default declaration before assignment`);
	return { declAt, assignAt, slice: source.slice(declAt, assignAt) };
}

function bundleHasAstra(source, pathForError) {
	return catalogSlice(source, pathForError).slice.includes(`id:"${MODEL_ID}"`);
}

function bundleHasMarker(source) {
	return source.includes(MARKER_PREFIX);
}

function bundleIsUpstream(source, pathForError) {
	const { slice } = catalogSlice(source, pathForError);
	return slice.includes(`id:"${MODEL_ID}"`) && !slice.includes(MARKER_PREFIX);
}

function insertBundleAstra(source, pathForError) {
	const { assignAt, slice } = catalogSlice(source, pathForError);
	if (slice.includes(`id:"${MODEL_ID}"`)) return source;
	if (source.slice(assignAt - 3, assignAt) !== "}};") {
		fail(`${pathForError} openai_codex_default does not end with }}; before OPENAI_CODEX_MODELS`);
	}
	const insertAt = assignAt - 3;
	return `${source.slice(0, insertAt)}${BUNDLE_INSERT}${source.slice(insertAt)}`;
}

function stripBundleAstra(source, pathForError) {
	const insert = source.includes(BUNDLE_INSERT) ? BUNDLE_INSERT : V2_INSERT;
	if (!source.includes(insert)) {
		fail(`${pathForError} has patch marker but insert payload is not a recognized revision`);
	}
	return source.replace(insert, "");
}

function backupPath(target) {
	return `${target}${BACKUP_SUFFIX}`;
}

function ensureBackup(target) {
	const backup = backupPath(target);
	if (!existsSync(backup)) {
		copyFileSync(target, backup);
		log(`backup written: ${backup}`);
	}
	return backup;
}

function restoreFromBackup(target) {
	const backup = backupPath(target);
	if (!existsSync(backup)) return false;
	copyFileSync(backup, target);
	log(`restored original from ${backup} (un-patched)`);
	return true;
}

function applyJson(path, owned) {
	const original = readFileSync(path, "utf8");
	if (jsonHasAstra(original, path)) {
		const { data, group } = parseCatalog(original, path);
		if (owned && group[MODEL_ID].contextWindow !== MODEL.contextWindow) {
			group[MODEL_ID].contextWindow = MODEL.contextWindow;
			writeFileSync(path, `${JSON.stringify(data)}\n`, "utf8");
			log(`json updated ${MODEL_ID} context window to ${MODEL.contextWindow}`);
			return { changed: true, backup: existsSync(backupPath(path)) ? backupPath(path) : undefined };
		}
		log(`json already has ${MODEL_ID}`);
		return { changed: false, backup: existsSync(backupPath(path)) ? backupPath(path) : undefined };
	}
	const backup = ensureBackup(path);
	const { data, group } = parseCatalog(original, path);
	group[MODEL_ID] = MODEL;
	const patched = `${JSON.stringify(data)}\n`;
	JSON.parse(patched);
	writeFileSync(path, patched, "utf8");
	if (!jsonHasAstra(readFileSync(path, "utf8"), path)) {
		fail(`post-patch json still missing ${MODEL_ID}. Restore from backup at ${backup}.`);
	}
	log(`json inserted ${MODEL_ID}`);
	return { changed: true, backup };
}

function applyBundle(path) {
	const original = readFileSync(path, "utf8");
	if (original.includes(V2_INSERT)) {
		writeFileSync(path, original.replace(V2_INSERT, BUNDLE_INSERT), "utf8");
		log(`bundle upgraded ${MODEL_ID} from v2 to v${PATCH_REVISION}`);
		return { changed: true, backup: existsSync(backupPath(path)) ? backupPath(path) : undefined };
	}
	if (bundleHasMarker(original) && !original.includes(BUNDLE_INSERT)) {
		fail(`unrecognized patch payload in ${path}; cannot safely upgrade`);
	}
	if (original.includes(BUNDLE_INSERT)) {
		log(`bundle already has ${MODEL_ID}`);
		return { changed: false, backup: existsSync(backupPath(path)) ? backupPath(path) : undefined };
	}
	if (bundleIsUpstream(original, path)) {
		log(`bundle already has unpatched ${MODEL_ID}`);
		return { changed: false, backup: existsSync(backupPath(path)) ? backupPath(path) : undefined };
	}
	const backup = ensureBackup(path);
	const patched = insertBundleAstra(original, path);
	writeFileSync(path, patched, "utf8");
	const verify = readFileSync(path, "utf8");
	if (!bundleHasAstra(verify, path) || !bundleHasMarker(verify)) {
		fail(`post-patch bundle still missing ${MODEL_ID}. Restore from backup at ${backup}.`);
	}
	log(`bundle inserted ${MODEL_ID} at revision ${PATCH_REVISION}`);
	return { changed: true, backup };
}

function unpatchJson(path) {
	if (!existsSync(path)) return;
	if (restoreFromBackup(path)) return;
	const raw = readFileSync(path, "utf8");
	if (!jsonHasAstra(raw, path)) return;
	const { data, group } = parseCatalog(raw, path);
	delete group[MODEL_ID];
	writeFileSync(path, `${JSON.stringify(data)}\n`, "utf8");
	log(`json removed ${MODEL_ID} (no backup)`);
}

function unpatchBundle(path) {
	if (!existsSync(path)) return;
	const raw = readFileSync(path, "utf8");
	if (!bundleHasMarker(raw)) return;
	if (restoreFromBackup(path)) return;
	writeFileSync(path, stripBundleAstra(raw, path), "utf8");
	log("bundle reversed current-revision insert (no backup)");
}

const jsonTarget = locateJsonTarget();
const bundleTarget = locateBundleTarget();
const versions = getInstalledVersions();

if (!jsonTarget && !bundleTarget) {
	if (checkOnly) fail("pi openai-codex catalog not installed; cannot verify patch");
	log("pi openai-codex catalog not installed — nothing to patch");
	process.exit(0);
}
if (!bundleTarget) {
	fail("CLI bundle catalog (openai_codex_default) not found; pi --list-models would not see this patch");
}
if (!jsonTarget) {
	fail("pi-ai openai-codex.json not found");
}

log(`profile=${profile || "(unset)"} bundle: ${bundleTarget}`);
log(`json:   ${jsonTarget}`);

const jsonRaw = readFileSync(jsonTarget, "utf8");
const bundleRaw = readFileSync(bundleTarget, "utf8");
const jsonPresent = jsonHasAstra(jsonRaw, jsonTarget);
const bundlePresent = bundleHasAstra(bundleRaw, bundleTarget);
const marked = bundleHasMarker(bundleRaw);
function unpatchedJsonHasId(path, liveRaw) {
	const backup = backupPath(path);
	if (existsSync(backup)) return jsonHasAstra(readFileSync(backup, "utf8"), backup);
	return jsonHasAstra(liveRaw, path);
}

function unpatchedBundleHasId(path, liveRaw) {
	const backup = backupPath(path);
	if (existsSync(backup)) return bundleHasAstra(readFileSync(backup, "utf8"), backup);
	return bundleIsUpstream(liveRaw, path);
}

const jsonUpstream = unpatchedJsonHasId(jsonTarget, jsonRaw);
const bundleUpstream = unpatchedBundleHasId(bundleTarget, bundleRaw);

if (!wantPatched) {
	if (checkOnly) {
		if (marked) fail(`profile '${profile || "(unset)"}' ≠ personal but bundle is patched`);
		log("profile ≠ personal; catalog unpatched as expected");
		process.exit(0);
	}
	if (!marked) {
		log("profile ≠ personal; nothing to do");
		writeStateFile({
			status: "unpatched",
			target: bundleTarget,
			jsonTarget,
			reason: `profile=${profile || "(unset)"}`,
		});
		process.exit(0);
	}
	unpatchBundle(bundleTarget);
	unpatchJson(jsonTarget);
	writeStateFile({
		status: "unpatched",
		target: bundleTarget,
		jsonTarget,
		reason: `profile=${profile || "(unset)"}`,
	});
	process.exit(0);
}

if (checkOnly) {
	const missing = [];
	if (!jsonPresent) missing.push(`json missing ${MODEL_ID}`);
	if (!bundlePresent) missing.push(`bundle missing ${MODEL_ID}`);
	if (marked) {
		if (!bundleRaw.includes(BUNDLE_INSERT)) missing.push(`bundle needs revision ${PATCH_REVISION}`);
		if (parseCatalog(jsonRaw, jsonTarget).group[MODEL_ID]?.contextWindow !== MODEL.contextWindow) {
			missing.push(`json context window must be ${MODEL.contextWindow}`);
		}
	}
	if (missing.length) fail(missing.join("; "));
	if (!marked && jsonUpstream && bundleUpstream) {
		log(`${MODEL_ID} is in the unpatched catalog — delete this patch (upstream caught up)`);
	} else {
		log(`catalog already has ${MODEL_ID} in json and bundle`);
	}
	process.exit(0);
}

if (jsonUpstream && bundleUpstream) {
	log(`${MODEL_ID} is in the unpatched catalog — delete this patch (upstream caught up)`);
	writeStateFile(
		stopgapState({
			status: "already-patched",
			target: bundleTarget,
			jsonTarget,
			version: versions.piAi,
			versions,
			patchRevision: PATCH_REVISION,
			reason: "upstream",
		}),
	);
	process.exit(0);
}

const bundleResult = applyBundle(bundleTarget);
const jsonResult = applyJson(jsonTarget, marked);

writeStateFile(
	stopgapState({
		status: "patched",
		target: bundleTarget,
		jsonTarget,
		backup: bundleResult.backup,
		jsonBackup: jsonResult.backup,
		version: versions.piAi,
		versions,
		patchRevision: PATCH_REVISION,
		fingerprintPre: sha256(bundleRaw),
		fingerprintPost: sha256(readFileSync(bundleTarget, "utf8")),
	}),
);
log(`patched at revision ${PATCH_REVISION} (${MODEL_ID} in json and CLI bundle)`);
process.exit(0);
