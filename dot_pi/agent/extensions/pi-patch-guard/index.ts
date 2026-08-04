/**
 * pi-patch-guard — pi extension: warn when a chezmoi-managed pi runtime patch
 * has been silently wiped by a pi self-update / `npm i -g` reinstall.
 *
 * Background: runtime patches (e.g. hide-nonbridge-claude-models) edit files
 * *inside* the installed `@earendil-works/pi-coding-agent` package. Any reinstall
 * of that package rewrites `dist/` and erases the edit. The re-apply only runs on
 * `chezmoi apply`, so between an out-of-band update and the next apply, the patch
 * is gone — non-bridge Claude models reappear in the picker/`--list-models`, and
 * fresh `pi` processes (subagents) read the unpatched file.
 *
 * This guard does NOT heal anything. It is a tripwire: at session start and
 * after each agent response it checks whether a patch that the state file says
 * *should* be applied is still present on disk. If not, it emits a UI warning
 * so you know to re-run the patch (`chezmoi apply` or the patch.mjs directly)
 * and reload.
 *
 * Scope decisions (intentional, keep it minimal):
 *   - Warn only. No disk writes, no `node` spawns, no subagent protection.
 *   - Interactive only (`ctx.hasUI`) — headless/subagent runs stay silent.
 *   - Fires on `session_start` (before you type) and `agent_end` (after the
 *     agent responds), and re-checks disk every time — so the reminder
 *     persists on every turn until the marker reappears.
 *   - Never throws into a turn: every path is wrapped.
 *
 * Source of truth: each patch's own state file under
 *   ~/.local/state/chezmoi-pi-patches/<patch>.json
 * which records `status` ("patched"/"already-patched" ⇒ intended-on) and the
 * resolved `target` file. We assert the target still contains the patch marker.
 *
 * Patches are auto-discovered by enumerating that state dir (no hardcoded list)
 * and deriving the marker from the convention `chezmoi-pi-patch:<name>`. This is
 * profile-aware for free: a patch gated off for the active chezmoi profile
 * writes `status:"unpatched"`, which is not intended-on ⇒ no drift.
 *
 * SECOND JOB — source assumptions (sentinels). Some extensions are written
 * against *unpatched* pi internals whose behavior is load-bearing but undocumented
 * (e.g. ntfy suppresses compaction notifications by relying on
 * `AgentSession.compact()` disconnecting extension handlers before aborting).
 * Those are not patches — nothing is edited — but they silently rot on a pi
 * upgrade. `assumptions.json` beside this module declares each one as a regex
 * over a file in the installed pi `dist/`; a non-match warns at session start.
 * Checked only on `session_start` (full-file reads are too costly per turn).
 */
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

/** Patches this guard watches. Marker is the literal string the patch injects. */
interface WatchedPatch {
	name: string;
	marker: string;
}

const STATE_DIR = path.join(os.homedir(), ".local", "state", "chezmoi-pi-patches");

/**
 * Auto-discover every chezmoi-pi-patch from its state file, instead of a
 * hardcoded list. Each patch writes `<stateDir>/<name>.json` on apply; the
 * marker it injects is the universal convention `chezmoi-pi-patch:<name>`
 * (overridable by a `marker` field in the state file). Discovery is
 * profile-aware for free: `checkPatchDrift` treats any non-intended-on `status`
 * (e.g. `unpatched` for a profile-gated patch that's off on this profile) as
 * no-drift, so patches inactive for the active profile self-exclude.
 *
 * Returns [] on any error (missing dir, unreadable) so the guard stays quiet.
 */
export function discoverWatchedPatches(
	deps: {
		readDir?: (p: string) => string[];
		readFile?: (p: string) => string;
		stateDir?: string;
	} = {},
): WatchedPatch[] {
	const readDir = deps.readDir ?? ((p) => fs.readdirSync(p));
	const readFile = deps.readFile ?? ((p) => fs.readFileSync(p, "utf-8"));
	const stateDir = deps.stateDir ?? STATE_DIR;
	try {
		return readDir(stateDir)
			.filter((f) => f.endsWith(".json"))
			.map((f) => {
				const fallbackName = f.slice(0, -".json".length);
				let name = fallbackName;
				let marker: string | undefined;
				try {
					const state = JSON.parse(readFile(path.join(stateDir, f))) as {
						patchName?: string;
						marker?: string;
					};
					if (state.patchName) name = state.patchName;
					if (state.marker) marker = state.marker;
				} catch {
					// Malformed json: keep filename-derived name; checkPatchDrift will
					// re-read and bail to no-drift anyway.
				}
				return { name, marker: marker ?? `chezmoi-pi-patch:${name}` };
			});
	} catch {
		return [];
	}
}

interface GuardConfig {
	enabled: boolean;
}

function extensionDir(): string {
	return path.dirname(fileURLToPath(import.meta.url));
}

/** Read config.json beside this module. Missing/unreadable ⇒ enabled. */
export function loadConfig(dir: string): GuardConfig {
	try {
		const raw = fs.readFileSync(path.join(dir, "config.json"), "utf-8");
		const parsed = JSON.parse(raw) as Partial<GuardConfig>;
		return { enabled: parsed.enabled !== false };
	} catch {
		return { enabled: true };
	}
}

export interface DriftResult {
	/** true ⇒ patch is intended-on but its marker is absent from the target. */
	drift: boolean;
	/** Human-readable patch name (for the warning). */
	name: string;
}

/**
 * Pure drift check for one patch. Returns drift=false on any ambiguity
 * (no state file, status not intended-on, target unresolved/unreadable) so the
 * guard never false-alarms.
 */
export function checkPatchDrift(
	patch: WatchedPatch,
	deps: {
		readFile?: (p: string) => string;
		exists?: (p: string) => boolean;
		stateDir?: string;
	} = {},
): DriftResult {
	const readFile = deps.readFile ?? ((p) => fs.readFileSync(p, "utf-8"));
	const exists = deps.exists ?? fs.existsSync;
	const stateDir = deps.stateDir ?? STATE_DIR;

	try {
		const stateFile = path.join(stateDir, `${patch.name}.json`);
		if (!exists(stateFile)) return { drift: false, name: patch.name };
		const state = JSON.parse(readFile(stateFile)) as { status?: string; target?: string };
		const intendedOn = state.status === "patched" || state.status === "already-patched";
		if (!intendedOn) return { drift: false, name: patch.name };
		const target = state.target;
		if (!target || !exists(target)) return { drift: false, name: patch.name };
		const content = readFile(target);
		return { drift: !content.includes(patch.marker), name: patch.name };
	} catch {
		return { drift: false, name: patch.name };
	}
}

/** One declared assumption about installed pi source. */
export interface SourceAssumption {
	name: string;
	/** Path relative to the pi package's `dist/` dir. */
	file: string;
	/** Regex source; must match the file for the assumption to hold. */
	pattern: string;
	flags?: string;
	message: string;
	/** pi version the pattern was last verified against (documentation only). */
	verifiedVersion?: string;
}

/** Read assumptions.json beside this module. Missing/malformed ⇒ [] (quiet). */
export function loadAssumptions(
	dir: string,
	deps: { readFile?: (p: string) => string } = {},
): SourceAssumption[] {
	const readFile = deps.readFile ?? ((p) => fs.readFileSync(p, "utf-8"));
	try {
		const parsed = JSON.parse(readFile(path.join(dir, "assumptions.json"))) as {
			assumptions?: SourceAssumption[];
		};
		return (parsed.assumptions ?? []).filter(
			(a) => typeof a?.name === "string" && typeof a?.file === "string" && typeof a?.pattern === "string",
		);
	} catch {
		return [];
	}
}

/**
 * Locate the installed pi package's `dist/` dir without importing it.
 * 1. any argv entry inside a `pi-coding-agent` package (the running cli.js);
 * 2. `<node>/../../lib/node_modules/@earendil-works/pi-coding-agent/dist`.
 * Returns undefined if neither resolves ⇒ assumption checks are skipped.
 */
export function resolvePiDistDir(
	deps: { argv?: string[]; execPath?: string; exists?: (p: string) => boolean } = {},
): string | undefined {
	const argv = deps.argv ?? process.argv;
	const execPath = deps.execPath ?? process.execPath;
	const exists = deps.exists ?? fs.existsSync;
	try {
		for (const arg of argv) {
			if (typeof arg !== "string") continue;
			const idx = arg.indexOf(`${path.sep}dist${path.sep}`);
			if (idx === -1 || !arg.includes("pi-coding-agent")) continue;
			const dist = arg.slice(0, idx + `${path.sep}dist`.length);
			if (exists(dist)) return dist;
		}
		const guess = path.join(
			path.dirname(path.dirname(execPath)),
			"lib",
			"node_modules",
			"@earendil-works",
			"pi-coding-agent",
			"dist",
		);
		return exists(guess) ? guess : undefined;
	} catch {
		return undefined;
	}
}

export interface AssumptionResult {
	name: string;
	/** true ⇒ the pattern no longer matches installed pi source. */
	broken: boolean;
}

/**
 * Pure assumption check. Returns broken=false on any ambiguity (no dist dir,
 * missing/unreadable file, bad regex) so the guard never false-alarms.
 */
export function checkAssumption(
	a: SourceAssumption,
	deps: { distDir?: string; readFile?: (p: string) => string; exists?: (p: string) => boolean } = {},
): AssumptionResult {
	const readFile = deps.readFile ?? ((p) => fs.readFileSync(p, "utf-8"));
	const exists = deps.exists ?? fs.existsSync;
	try {
		const distDir = deps.distDir ?? resolvePiDistDir();
		if (!distDir) return { name: a.name, broken: false };
		const target = path.join(distDir, a.file);
		if (!exists(target)) return { name: a.name, broken: false };
		const re = new RegExp(a.pattern, a.flags ?? "");
		return { name: a.name, broken: !re.test(readFile(target)) };
	} catch {
		return { name: a.name, broken: false };
	}
}

export default function (pi: ExtensionAPI): void {
	const cfg = loadConfig(extensionDir());

	/** Check every watched patch and warn (once per invocation) for any that drifted. */
	const warnOnDrift = (ctx: any): void => {
		try {
			if (!cfg.enabled || !ctx?.hasUI) return;
			for (const patch of discoverWatchedPatches()) {
				const { drift } = checkPatchDrift(patch);
				if (!drift) continue;
				ctx.ui.notify(
					`⚠ pi patch "${patch.name}" is missing on disk — likely wiped by a pi update. ` +
						`Re-run it (chezmoi apply or the patch.mjs) and reload pi; fresh subagents read the unpatched file until then.`,
					"warning",
				);
			}
		} catch {
			// Never let the guard break a turn.
		}
	};

	/** Check declared source assumptions against installed pi dist; warn on breaks. */
	const warnOnBrokenAssumptions = (ctx: any): void => {
		try {
			if (!cfg.enabled || !ctx?.hasUI) return;
			for (const a of loadAssumptions(extensionDir())) {
				if (!checkAssumption(a).broken) continue;
				ctx.ui.notify(
					`⚠ pi source assumption "${a.name}" no longer holds in ${a.file}` +
						(a.verifiedVersion ? ` (last verified on pi ${a.verifiedVersion})` : "") +
						`. ${a.message}`,
					"warning",
				);
			}
		} catch {
			// Never let the guard break a turn.
		}
	};

	// Session open/reload/resume — surface drift before the user types.
	pi.on("session_start", async (_event: unknown, ctx: any) => {
		warnOnDrift(ctx);
		warnOnBrokenAssumptions(ctx);
	});
	// After the agent finishes responding — re-check disk so the reminder persists each turn.
	pi.on("agent_end", async (_event: unknown, ctx: any) => warnOnDrift(ctx));
}
