/**
 * Sidecar runtime state for the issue extension.
 *
 * Layered config (later wins): DEFAULTS -> config.json (chezmoi-managed,
 * beside this module) -> state.json (NOT chezmoi-managed, runtime overrides).
 *
 * state.json is never a chezmoi *source* file and the deployed dir is not an
 * `exact_` dir, so `chezmoi apply` never creates, tracks, or removes it. This
 * mirrors the ntfy / hindsight sidecar idiom and is why runtime edits here
 * survive `chezmoi apply` (unlike the pre-existing in-memory-only on/off).
 */
import * as fs from "node:fs";
import * as path from "node:path";

const STATE_FILE = "state.json";

export interface RuntimeState {
	/** Runtime on/off override. Wins over config.json `enabled`. */
	enabled?: boolean;
	/** provider/id used for issue drafts and checkpoint summaries. */
	summaryModel?: string;
}

/** Read + validate the sidecar. Missing/unreadable/invalid -> empty. Pure-ish. */
export function loadRuntimeState(dir: string): RuntimeState {
	let parsed: unknown;
	try {
		parsed = JSON.parse(fs.readFileSync(path.join(dir, STATE_FILE), "utf8"));
	} catch {
		return {};
	}
	// Guard against valid-but-non-object JSON (null, arrays, scalars): reading a
	// property off `null` would throw here and crash extension startup.
	if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return {};
	const p = parsed as Record<string, unknown>;
	const out: RuntimeState = {};
	if (typeof p.enabled === "boolean") out.enabled = p.enabled;
	if (typeof p.summaryModel === "string" && p.summaryModel.trim()) {
		out.summaryModel = p.summaryModel.trim();
	}
	return out;
}

/**
 * Merge `patch` into the existing sidecar and persist atomically (temp file +
 * rename) so a crash mid-write can't leave corrupt JSON. Returns the merged
 * state. Throws on I/O failure — callers update in-memory state only after this
 * resolves, so memory and disk never diverge.
 */
export function saveRuntimeState(dir: string, patch: RuntimeState): RuntimeState {
	const next: RuntimeState = { ...loadRuntimeState(dir), ...patch };
	const target = path.join(dir, STATE_FILE);
	const tmp = `${target}.${process.pid}.tmp`;
	fs.writeFileSync(tmp, `${JSON.stringify(next, null, 2)}\n`);
	try {
		fs.renameSync(tmp, target);
	} catch (err) {
		// Don't leak the temp file if the atomic rename fails; target is untouched.
		try {
			fs.rmSync(tmp, { force: true });
		} catch {
			/* best effort */
		}
		throw err;
	}
	return next;
}

/** Effective on/off: sidecar override wins over the config.json default. */
export function effectiveEnabled(dir: string, configDefault: boolean): boolean {
	const s = loadRuntimeState(dir);
	return typeof s.enabled === "boolean" ? s.enabled : configDefault;
}

/** Effective issue LLM model: sidecar wins over the config.json default. */
export function effectiveSummaryModel(dir: string, configDefault?: string): string | undefined {
	return loadRuntimeState(dir).summaryModel ?? configDefault;
}
