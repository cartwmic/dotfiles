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
 * This guard does NOT heal anything. It is a tripwire: on each user turn it
 * checks whether a patch that the state file says *should* be applied is still
 * present on disk. If not, it emits a single UI warning so you know to re-run
 * the patch (`chezmoi apply` or the patch.mjs directly) and reload.
 *
 * Scope decisions (intentional, keep it minimal):
 *   - Warn only. No disk writes, no `node` spawns, no subagent protection.
 *   - Interactive only (`ctx.hasUI`) — headless/subagent runs stay silent.
 *   - Warns once per drift episode; re-arms automatically once the marker
 *     reappears on disk (so a later re-break warns again).
 *   - Never throws into a turn: every path is wrapped.
 *
 * Source of truth: the patch's own state file under
 *   ~/.local/state/chezmoi-pi-patches/<patch>.json
 * which records `status` ("patched"/"already-patched" ⇒ intended-on) and the
 * resolved `target` file. We assert the target still contains the patch marker.
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

const WATCHED: WatchedPatch[] = [
	{
		name: "hide-nonbridge-claude-models",
		marker: "chezmoi-pi-patch:hide-nonbridge-claude-models",
	},
];

const STATE_DIR = path.join(os.homedir(), ".local", "state", "chezmoi-pi-patches");

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

export default function (pi: ExtensionAPI): void {
	const cfg = loadConfig(extensionDir());
	// Names currently in a warned (drift-detected) state, to warn once per episode.
	const warned = new Set<string>();

	pi.on("before_agent_start", async (_event: unknown, ctx: any) => {
		try {
			if (!cfg.enabled || !ctx?.hasUI) return;
			for (const patch of WATCHED) {
				const { drift } = checkPatchDrift(patch);
				if (drift) {
					if (!warned.has(patch.name)) {
						warned.add(patch.name);
						ctx.ui.notify(
							`⚠ pi patch "${patch.name}" is missing on disk — likely wiped by a pi update. ` +
								`Re-run it (chezmoi apply or the patch.mjs) and reload pi; fresh subagents read the unpatched file until then.`,
							"warning",
						);
					}
				} else {
					// Marker back (or ambiguous) ⇒ re-arm so a later re-break warns again.
					warned.delete(patch.name);
				}
			}
		} catch {
			// Never let the guard break a turn.
		}
	});
}
