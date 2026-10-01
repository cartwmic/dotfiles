import { createHash, randomUUID } from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { setReviewStatus as transitionReviewStatus } from "./core/index.mjs";

const STATE_VERSION = 1;
const RECORD_VERSION = 1;
const STATUS_VALUES = new Set(["open", "kept", "dismissed"]);
const OPERATIONAL_FIELDS = new Set(["enabled", "cursor", "focus", "modelOverride", "workerSession"]);
const locks = new Map();

function requiredText(value, name) {
	if (typeof value !== "string" || value.trim() === "") throw new TypeError(`${name} must be a non-empty string`);
	return value.trim();
}

function optionalText(value, name) {
	if (value === null || value === undefined) return null;
	if (typeof value !== "string") throw new TypeError(`${name} must be a string or null`);
	const result = value.trim();
	return result || null;
}

function requiredContent(value, name) {
	if (typeof value !== "string" || value.trim() === "") throw new TypeError(`${name} must be non-empty text`);
	return value;
}

function optionalContent(value, name) {
	if (value === null || value === undefined) return undefined;
	if (typeof value !== "string") throw new TypeError(`${name} must be text`);
	return value.trim() ? value : undefined;
}

function cloneJson(value, name) {
	const serialized = JSON.stringify(value);
	if (serialized === undefined) throw new TypeError(`${name} must be JSON-serializable`);
	return JSON.parse(serialized);
}

function canonicalJson(value) {
	if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
	if (value && typeof value === "object") {
		return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(",")}}`;
	}
	return JSON.stringify(value);
}

function sourceKey(sourceId) {
	return createHash("sha256").update(sourceId).digest("hex");
}

function recordKey(recordId) {
	return createHash("sha256").update(recordId).digest("hex");
}

function withLock(key, operation) {
	const previous = locks.get(key) ?? Promise.resolve();
	let release;
	const current = new Promise((resolve) => { release = resolve; });
	locks.set(key, current);
	return previous.catch(() => {}).then(operation).finally(() => {
		release();
		if (locks.get(key) === current) locks.delete(key);
	});
}

async function atomicWriteFile(filename, content) {
	const directory = path.dirname(filename);
	await fs.mkdir(directory, { recursive: true, mode: 0o700 });
	const temporary = `${filename}.${process.pid}.${randomUUID()}.tmp`;
	let handle;
	try {
		handle = await fs.open(temporary, "wx", 0o600);
		await handle.writeFile(content, "utf8");
		await handle.sync();
		await handle.close();
		handle = undefined;
		await fs.rename(temporary, filename);
		const directoryHandle = await fs.open(directory, "r");
		try {
			await directoryHandle.sync();
		} finally {
			await directoryHandle.close();
		}
	} catch (error) {
		if (handle) await handle.close().catch(() => {});
		await fs.rm(temporary, { force: true }).catch(() => {});
		throw error;
	}
}

function recordedTime(value) {
	if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z$/.test(value)) return undefined;
	const date = new Date(value);
	return Number.isFinite(date.getTime()) && date.toISOString() === value.replace(/Z$/, value.includes(".") ? "Z" : ".000Z") ? value : undefined;
}

function normalizeRecord(record, expectedSourceId) {
	if (!record || typeof record !== "object" || Array.isArray(record)) throw new TypeError("record must be an object");
	const id = requiredText(record.id, "record.id");
	const proposalKey = requiredText(record.proposalKey, "record.proposalKey");
	if (record.type !== "friction" && record.type !== "improvement") throw new TypeError("record.type must be friction or improvement");
	if (!STATUS_VALUES.has(record.status)) throw new TypeError("record.status must be open, kept, or dismissed");
	const observation = requiredContent(record.observation, "record.observation");
	const recommendation = optionalContent(record.recommendation, "record.recommendation");
	if (!Array.isArray(record.evidence)) throw new TypeError("record.evidence must be an array");
	if (expectedSourceId && record.evidence.some((item) => item?.sourceId !== expectedSourceId)) {
		throw new Error(`record evidence is not scoped to source ${expectedSourceId}`);
	}
	if (!Array.isArray(record.reviewHistory)) throw new TypeError("record.reviewHistory must be an array");
	if (!Array.isArray(record.analogues)) throw new TypeError("record.analogues must be an array");
	return {
		...cloneJson(record, "record"),
		id,
		proposalKey,
		recordedAt: recordedTime(record.recordedAt),
		observation,
		...(recommendation ? { recommendation } : { recommendation: undefined }),
	};
}

function metadataFor(sourceId, record) {
	return {
		formatVersion: RECORD_VERSION,
		sourceId,
		id: record.id,
		proposalKey: record.proposalKey,
		type: record.type,
		recordedAt: record.recordedAt,
		reviewHistory: record.reviewHistory,
		evidence: record.evidence,
		evidenceAssessment: record.evidenceAssessment,
		analogues: record.analogues,
	};
}

function inlineCode(value) {
	const text = String(value);
	const longestRun = Math.max(0, ...[...text.matchAll(/`+/g)].map(([run]) => run.length));
	const fence = "`".repeat(longestRun + 1);
	return `${fence}${text.includes("`") ? ` ${text} ` : text}${fence}`;
}

function quoteText(value) {
	return String(value).split("\n").map((line) => `> ${line.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")}`).join("\n");
}

function renderEvidence(record) {
	const lines = [];
	for (const evidence of record.evidence) {
		lines.push(`### ${evidence.sourceLabel ?? evidence.sourceId} — ${evidence.evidenceId}`);
		lines.push(quoteText(evidence.summary));
		lines.push(`- Outcome: ${inlineCode(evidence.outcome ?? "unknown")}`);
		lines.push(`- Source: ${inlineCode(evidence.provenance?.pointer ?? "unavailable")}`);
		lines.push(`- Pointer availability: ${inlineCode(evidence.provenance?.availability ?? "unknown")}`);
		if (evidence.provenance?.context) lines.push(`- Context: ${inlineCode(evidence.provenance.context)}`);
		if (evidence.occurredAt) lines.push(`- Occurred: ${inlineCode(evidence.occurredAt)}`);
		lines.push("");
	}
	for (const analogue of record.analogues) {
		lines.push(`### Possible analogue — ${analogue.sourceLabel}`);
		lines.push(quoteText(analogue.summary));
		if (analogue.sourcePointer) lines.push(`- Reference: ${inlineCode(analogue.sourcePointer)}`);
		lines.push("- Not verified as a local occurrence.", "");
	}
	return lines.join("\n").trimEnd();
}

function renderHistory(record) {
	return record.reviewHistory.map((event) => {
		const details = [event.at, event.reason].filter(Boolean).map(inlineCode);
		return `- ${event.status}${details.length ? ` — ${details.join("; ")}` : ""}`;
	}).join("\n");
}

function renderSection(name, content) {
	return `<!-- learnings-monitor:begin:${name} -->\n${content ?? ""}\n<!-- learnings-monitor:end:${name} -->`;
}

function renderRecord(sourceId, inputRecord) {
	const record = normalizeRecord(inputRecord, sourceId);
	const metadata = JSON.stringify(metadataFor(sourceId, record), null, 2).replaceAll("--", "\\u002d\\u002d");
	return [
		"# Learning opportunity",
		"",
		`**Status:** ${record.status}`,
		`**Type:** ${record.type}`,
		`**Evidence claim:** ${record.evidenceAssessment?.claim ?? "unknown"}`,
		"",
		"## Observation",
		renderSection("observation", record.observation),
		"",
		"## Recommendation",
		renderSection("recommendation", record.recommendation ?? ""),
		"",
		"## Evidence",
		renderSection("evidence", renderEvidence(record)),
		"",
		"## Review history",
		renderSection("history", renderHistory(record)),
		"",
		`<!-- learnings-monitor:metadata\n${metadata}\n-->`,
		"",
	].join("\n");
}

function readSection(markdown, name) {
	const start = `<!-- learnings-monitor:begin:${name} -->`;
	const end = `<!-- learnings-monitor:end:${name} -->`;
	const startAt = markdown.indexOf(start);
	const endAt = startAt < 0 ? -1 : markdown.indexOf(end, startAt + start.length);
	if (startAt < 0 || endAt < 0 || markdown.indexOf(start, startAt + start.length) >= 0) {
		throw new Error(`record Markdown is missing a unique ${name} section`);
	}
	let content = markdown.slice(startAt + start.length, endAt);
	if (content.startsWith("\r\n")) content = content.slice(2);
	else if (content.startsWith("\n")) content = content.slice(1);
	if (content.endsWith("\r\n")) content = content.slice(0, -2);
	else if (content.endsWith("\n")) content = content.slice(0, -1);
	return content;
}

function parseRecordMarkdown(markdown, expectedSourceId) {
	const start = "<!-- learnings-monitor:metadata\n";
	const startAt = markdown.indexOf(start);
	const endAt = startAt < 0 ? -1 : markdown.indexOf("\n-->", startAt + start.length);
	if (startAt < 0 || endAt < 0 || markdown.indexOf(start, startAt + start.length) >= 0) {
		throw new Error("record Markdown has missing or duplicate storage metadata");
	}
	let metadata;
	try {
		metadata = JSON.parse(markdown.slice(startAt + start.length, endAt));
	} catch (error) {
		throw new Error(`record Markdown metadata is invalid JSON: ${error.message}`);
	}
	if (metadata?.formatVersion !== RECORD_VERSION || metadata.sourceId !== expectedSourceId) {
		throw new Error("record Markdown metadata has an unsupported version or source");
	}
	const statusMatch = markdown.match(/^\*\*Status:\*\*\s*(open|kept|dismissed)\s*$/m);
	if (!statusMatch) throw new Error("record Markdown has no valid status line");
	const record = normalizeRecord({
		id: metadata.id,
		proposalKey: metadata.proposalKey,
		type: metadata.type,
		recordedAt: metadata.recordedAt,
		status: statusMatch[1],
		observation: readSection(markdown, "observation"),
		recommendation: readSection(markdown, "recommendation"),
		reviewHistory: metadata.reviewHistory,
		evidence: metadata.evidence,
		evidenceAssessment: metadata.evidenceAssessment,
		analogues: metadata.analogues,
	}, expectedSourceId);
	const lastReview = record.reviewHistory.at(-1)?.status;
	if (record.status !== "open" && lastReview !== record.status) {
		record.reviewHistory = [...record.reviewHistory, { status: record.status }];
	} else if (record.status === "open" && lastReview && lastReview !== "open") {
		record.reviewHistory = [...record.reviewHistory, { status: "open" }];
	}
	return record;
}

function replaceSection(markdown, name, content) {
	const start = `<!-- learnings-monitor:begin:${name} -->`;
	const end = `<!-- learnings-monitor:end:${name} -->`;
	const startAt = markdown.indexOf(start);
	const endAt = startAt < 0 ? -1 : markdown.indexOf(end, startAt + start.length);
	if (startAt < 0 || endAt < 0) throw new Error(`record Markdown is missing ${name} section`);
	return `${markdown.slice(0, startAt)}${renderSection(name, content)}${markdown.slice(endAt + end.length)}`;
}

function updateRecordMarkdown(markdown, sourceId, inputRecord, { updateStatus = false } = {}) {
	const record = normalizeRecord(inputRecord, sourceId);
	const metadataStart = "<!-- learnings-monitor:metadata\n";
	const metadataAt = markdown.indexOf(metadataStart);
	const metadataEnd = metadataAt < 0 ? -1 : markdown.indexOf("\n-->", metadataAt + metadataStart.length);
	if (metadataAt < 0 || metadataEnd < 0) throw new Error("record Markdown has no storage metadata");
	const metadata = JSON.stringify(metadataFor(sourceId, record), null, 2).replaceAll("--", "\\u002d\\u002d");
	let updated = `${markdown.slice(0, metadataAt)}<!-- learnings-monitor:metadata\n${metadata}\n-->${markdown.slice(metadataEnd + 4)}`;
	updated = updated.replace(/^\*\*Evidence claim:\*\*.*$/m, `**Evidence claim:** ${record.evidenceAssessment?.claim ?? "unknown"}`);
	updated = replaceSection(updated, "evidence", renderEvidence(record));
	updated = replaceSection(updated, "history", renderHistory(record));
	if (updateStatus) {
		const statusLine = /^\*\*Status:\*\*\s*(?:open|kept|dismissed)\s*$/m;
		if (!statusLine.test(updated)) throw new Error("record Markdown has no valid status line");
		updated = updated.replace(statusLine, `**Status:** ${record.status}`);
	}
	return updated;
}

function evidenceAssessment(record) {
	const count = new Set(record.evidence.map((item) => item?.key).filter((key) => typeof key === "string")).size;
	if (record.type === "improvement" && count >= 2) {
		return { claim: "recurring", distinctEvidenceCount: count, statement: `This workflow pattern is supported by ${count} distinct pieces of source evidence.` };
	}
	if (record.type === "improvement") {
		return { claim: "prospective", distinctEvidenceCount: count, statement: "A plausible future improvement is suggested by one observed source event; recurrence is not established." };
	}
	return {
		claim: "observed",
		distinctEvidenceCount: count,
		statement: count === 1 ? "Concrete friction was observed in one source event." : `Concrete friction was observed in ${count} distinct pieces of source evidence.`,
	};
}

function mergeUnique(existing, additions, key) {
	const result = [...existing];
	const seen = new Set(result.map((item) => item?.[key]).filter((value) => typeof value === "string"));
	for (const item of additions) {
		const value = item?.[key];
		if (typeof value === "string" && !seen.has(value)) {
			result.push(item);
			seen.add(value);
		}
	}
	return result;
}

function mergeGeneratedRecord(current, generated, basedOn) {
	const evidence = mergeUnique(current.evidence, generated.evidence, "key");
	const analogues = mergeUnique(current.analogues, generated.analogues, "id");
	const statusChangedByObserver = basedOn && generated.status !== basedOn.status && current.status === basedOn.status;
	const status = statusChangedByObserver ? generated.status : current.status;
	let reviewHistory = [...current.reviewHistory];
	if (statusChangedByObserver && Array.isArray(basedOn.reviewHistory)) {
		const baseHistory = new Set(basedOn.reviewHistory.map(canonicalJson));
		const newEvents = generated.reviewHistory.filter((event) => !baseHistory.has(canonicalJson(event)));
		// Review events have no required ID, so merge them by their serialized value.
		const historySeen = new Set(current.reviewHistory.map(canonicalJson));
		for (const event of newEvents) if (!historySeen.has(canonicalJson(event))) {
			reviewHistory.push(event);
			historySeen.add(canonicalJson(event));
		}
	}
	const merged = {
		...current,
		status,
		evidence,
		analogues,
		reviewHistory,
	};
	merged.evidenceAssessment = evidenceAssessment(merged);
	return { record: merged, updateStatus: statusChangedByObserver };
}

function initialOperationalState(sourceId) {
	return { version: STATE_VERSION, sourceId, enabled: false, cursor: null, pending: [], focus: null, modelOverride: null, workerSession: null };
}

function validateOperationalState(value, sourceId) {
	if (!value || typeof value !== "object" || Array.isArray(value) || value.version !== STATE_VERSION || value.sourceId !== sourceId) {
		throw new Error(`operational state for ${sourceId} has an unsupported version or source`);
	}
	if (typeof value.enabled !== "boolean" || !Array.isArray(value.pending)) throw new Error(`operational state for ${sourceId} is malformed`);
	const pending = value.pending.map((batch) => {
		if (!batch || typeof batch !== "object" || Array.isArray(batch)) throw new Error("pending batch must be an object");
		const result = { id: requiredText(batch.id, "pending batch id"), payload: cloneJson(batch.payload, "pending batch payload") };
		if (Object.hasOwn(batch, "cursorAfter")) result.cursorAfter = cloneJson(batch.cursorAfter, "pending batch cursorAfter");
		return result;
	});
	return {
		version: STATE_VERSION,
		sourceId,
		enabled: value.enabled,
		cursor: cloneJson(value.cursor ?? null, "cursor"),
		pending,
		focus: optionalText(value.focus, "focus"),
		modelOverride: optionalText(value.modelOverride, "modelOverride"),
		workerSession: optionalText(value.workerSession, "workerSession"),
	};
}

/** Default local root is outside the chezmoi source: $XDG_DATA_HOME/pi/learnings-monitor. */
export function defaultStoreRoot({ env = process.env, home = os.homedir() } = {}) {
	const xdgDataHome = typeof env.XDG_DATA_HOME === "string" && path.isAbsolute(env.XDG_DATA_HOME) ? env.XDG_DATA_HOME : null;
	const dataHome = xdgDataHome ?? path.join(home, ".local", "share");
	return path.join(dataHome, "pi", "learnings-monitor");
}

/**
 * Create the machine-local Markdown and operational-state store.
 * Records live under sources/<sha256(sourceId)>/records/*.md; the adjacent
 * operational.json stores only enabled, cursor, pending, focus, modelOverride,
 * and workerSession. All writes are private-mode atomic replacements.
 */
export function createLearningStore({ root = defaultStoreRoot() } = {}) {
	const storeRoot = path.resolve(root);
	const sourcesRoot = path.join(storeRoot, "sources");
	const directoryFor = (sourceId) => path.join(sourcesRoot, sourceKey(requiredText(sourceId, "sourceId")));
	const statePathFor = (sourceId) => path.join(directoryFor(sourceId), "operational.json");
	const recordPathFor = (sourceId, id) => path.join(directoryFor(sourceId), "records", `${recordKey(requiredText(id, "record id"))}.md`);

	async function ensureSource(sourceId, label) {
		const normalizedId = requiredText(sourceId, "sourceId");
		const directory = directoryFor(normalizedId);
		await fs.mkdir(directory, { recursive: true, mode: 0o700 });
		const manifestPath = path.join(directory, "source.json");
		let manifest;
		let shouldWrite = false;
		try {
			manifest = JSON.parse(await fs.readFile(manifestPath, "utf8"));
		} catch (error) {
			if (error.code !== "ENOENT") throw error;
			manifest = { sourceId: normalizedId, label: normalizedId };
			shouldWrite = true;
		}
		if (manifest.sourceId !== normalizedId) throw new Error("source directory hash collision or corrupt source manifest");
		const normalizedLabel = optionalText(label, "source label");
		if (normalizedLabel && normalizedLabel !== manifest.label) {
			manifest.label = normalizedLabel;
			shouldWrite = true;
		}
		if (shouldWrite) await atomicWriteFile(manifestPath, `${JSON.stringify({ sourceId: normalizedId, label: manifest.label }, null, 2)}\n`);
		return { sourceId: normalizedId, directory, label: manifest.label };
	}

	async function readState(sourceId) {
		try {
			const value = JSON.parse(await fs.readFile(statePathFor(sourceId), "utf8"));
			return validateOperationalState(value, sourceId);
		} catch (error) {
			if (error.code === "ENOENT") return initialOperationalState(sourceId);
			throw error;
		}
	}

	async function writeState(state) {
		await atomicWriteFile(statePathFor(state.sourceId), `${JSON.stringify(state, null, 2)}\n`);
	}

	async function readRecordAt(sourceId, filename) {
		return parseRecordMarkdown(await fs.readFile(filename, "utf8"), sourceId);
	}

	async function readRecordsUnlocked(sourceId) {
		const directory = path.join(directoryFor(sourceId), "records");
		let names;
		try {
			names = await fs.readdir(directory);
		} catch (error) {
			if (error.code === "ENOENT") return [];
			throw error;
		}
		const records = [];
		for (const name of names.filter((candidate) => candidate.endsWith(".md")).sort()) {
			records.push(await readRecordAt(sourceId, path.join(directory, name)));
		}
		return records;
	}

	return {
		root: storeRoot,

		getSourceDirectory(sourceId) {
			return directoryFor(sourceId);
		},

		async listSources() {
			let entries;
			try {
				entries = await fs.readdir(sourcesRoot, { withFileTypes: true });
			} catch (error) {
				if (error.code === "ENOENT") return [];
				throw error;
			}
			const sources = [];
			for (const entry of entries.filter((item) => item.isDirectory())) {
				const directory = path.join(sourcesRoot, entry.name);
				try {
					const manifest = JSON.parse(await fs.readFile(path.join(directory, "source.json"), "utf8"));
					if (sourceKey(manifest.sourceId) !== entry.name || typeof manifest.label !== "string") continue;
					const records = await readRecordsUnlocked(manifest.sourceId);
					const state = await readState(manifest.sourceId);
					sources.push({ sourceId: manifest.sourceId, label: manifest.label, path: directory, recordCount: records.length, enabled: state.enabled, pendingCount: state.pending.length });
				} catch (error) {
					if (error.code !== "ENOENT") throw error;
				}
			}
			return sources.sort((a, b) => a.label.localeCompare(b.label) || a.sourceId.localeCompare(b.sourceId));
		},

		async readRecords(sourceId) {
			const normalizedId = requiredText(sourceId, "sourceId");
			return readRecordsUnlocked(normalizedId);
		},

		async getRecord(sourceId, id) {
			const normalizedId = requiredText(sourceId, "sourceId");
			try {
				return await readRecordAt(normalizedId, recordPathFor(normalizedId, id));
			} catch (error) {
				if (error.code === "ENOENT") return null;
				throw error;
			}
		},

		/**
		 * Persist changed core records, merging into fresh Markdown at write time.
		 * Pass the exact records supplied to reviewActivity as basedOn so a generated
		 * dismissal-reopen transition can be distinguished from a newer owner edit.
		 */
		async applyChanges(sourceId, changes, { basedOn = [], label } = {}) {
			const normalizedId = requiredText(sourceId, "sourceId");
			if (!Array.isArray(changes)) throw new TypeError("changes must be an array");
			if (!Array.isArray(basedOn)) throw new TypeError("basedOn must be an array");
			return withLock(directoryFor(normalizedId), async () => {
				await ensureSource(normalizedId, label);
				const bases = new Map(basedOn.filter((item) => item && typeof item.id === "string").map((item) => [item.id, item]));
				const written = [];
				for (const candidate of changes) {
					const generated = normalizeRecord(candidate, normalizedId);
					const filename = recordPathFor(normalizedId, generated.id);
					let current;
					let markdown;
					try {
						markdown = await fs.readFile(filename, "utf8");
						current = parseRecordMarkdown(markdown, normalizedId);
					} catch (error) {
						if (error.code !== "ENOENT") throw error;
					}
					if (!current) {
						generated.recordedAt = new Date().toISOString();
						const content = renderRecord(normalizedId, generated);
						await atomicWriteFile(filename, content);
						written.push(generated);
						continue;
					}
					const merged = mergeGeneratedRecord(current, generated, bases.get(generated.id));
					await atomicWriteFile(filename, updateRecordMarkdown(markdown, normalizedId, merged.record, { updateStatus: merged.updateStatus }));
					written.push(merged.record);
				}
				return written;
			});
		},

		/** Read the current Markdown decision, append review history, and atomically save it. */
		async setReviewStatus(sourceId, id, status, { at } = {}) {
			const normalizedId = requiredText(sourceId, "sourceId");
			if (status !== "kept" && status !== "dismissed") throw new TypeError("status must be kept or dismissed");
			return withLock(directoryFor(normalizedId), async () => {
				const filename = recordPathFor(normalizedId, id);
				const markdown = await fs.readFile(filename, "utf8");
				const current = parseRecordMarkdown(markdown, normalizedId);
				const updated = transitionReviewStatus(current, status, { at });
				await atomicWriteFile(filename, updateRecordMarkdown(markdown, normalizedId, updated, { updateStatus: true }));
				return updated;
			});
		},

		async markSourceUnavailable(sourceId) {
			const normalizedId = requiredText(sourceId, "sourceId");
			return withLock(directoryFor(normalizedId), async () => {
				const records = await readRecordsUnlocked(normalizedId);
				let changed = 0;
				for (const listedRecord of records) {
					const filename = recordPathFor(normalizedId, listedRecord.id);
					const markdown = await fs.readFile(filename, "utf8");
					const record = parseRecordMarkdown(markdown, normalizedId);
					const evidence = record.evidence.map((item) => {
						if (item.provenance?.availability === "unavailable") return item;
						changed++;
						return { ...item, provenance: { ...item.provenance, availability: "unavailable" } };
					});
					if (evidence.some((item, index) => item !== record.evidence[index])) {
						await atomicWriteFile(filename, updateRecordMarkdown(markdown, normalizedId, { ...record, evidence }, {}));
					}
				}
				return changed;
			});
		},

		async getOperationalState(sourceId) {
			const normalizedId = requiredText(sourceId, "sourceId");
			return cloneJson(await readState(normalizedId), "operational state");
		},

		/** Update only named operational fields; pending work changes via queue methods. */
		async updateOperationalState(sourceId, patch) {
			const normalizedId = requiredText(sourceId, "sourceId");
			if (!patch || typeof patch !== "object" || Array.isArray(patch)) throw new TypeError("patch must be an object");
			for (const key of Object.keys(patch)) if (!OPERATIONAL_FIELDS.has(key)) throw new TypeError(`unsupported operational field: ${key}`);
			return withLock(directoryFor(normalizedId), async () => {
				await ensureSource(normalizedId);
				const state = await readState(normalizedId);
				if (Object.hasOwn(patch, "enabled")) {
					if (typeof patch.enabled !== "boolean") throw new TypeError("enabled must be a boolean");
					state.enabled = patch.enabled;
				}
				if (Object.hasOwn(patch, "cursor")) state.cursor = cloneJson(patch.cursor, "cursor");
				if (Object.hasOwn(patch, "focus")) state.focus = optionalText(patch.focus, "focus");
				if (Object.hasOwn(patch, "modelOverride")) state.modelOverride = optionalText(patch.modelOverride, "modelOverride");
				if (Object.hasOwn(patch, "workerSession")) state.workerSession = optionalText(patch.workerSession, "workerSession");
				await writeState(state);
				return cloneJson(state, "operational state");
			});
		},

		/** Add a durable batch once. Reusing an ID with different content is an error. */
		async enqueuePending(sourceId, batch) {
			const normalizedId = requiredText(sourceId, "sourceId");
			if (!batch || typeof batch !== "object" || Array.isArray(batch)) throw new TypeError("batch must be an object");
			const next = { id: requiredText(batch.id, "batch.id"), payload: cloneJson(batch.payload, "batch.payload") };
			if (Object.hasOwn(batch, "cursorAfter")) next.cursorAfter = cloneJson(batch.cursorAfter, "batch.cursorAfter");
			return withLock(directoryFor(normalizedId), async () => {
				await ensureSource(normalizedId);
				const state = await readState(normalizedId);
				const existing = state.pending.find((item) => item.id === next.id);
				if (existing) {
					if (canonicalJson(existing) !== canonicalJson(next)) throw new Error(`pending batch ID collision: ${next.id}`);
					return cloneJson(state, "operational state");
				}
				state.pending.push(next);
				await writeState(state);
				return cloneJson(state, "operational state");
			});
		},

		/** Remove only the queue head and advance its cursor in the same atomic state write. */
		async completePending(sourceId, batchId) {
			const normalizedId = requiredText(sourceId, "sourceId");
			const normalizedBatchId = requiredText(batchId, "batchId");
			return withLock(directoryFor(normalizedId), async () => {
				const state = await readState(normalizedId);
				if (state.pending[0]?.id !== normalizedBatchId) throw new Error(`pending batch is not the queue head: ${normalizedBatchId}`);
				const [completed] = state.pending.splice(0, 1);
				if (Object.hasOwn(completed, "cursorAfter")) state.cursor = completed.cursorAfter;
				await writeState(state);
				return cloneJson(state, "operational state");
			});
		},

		/** Explicitly remove one source's records, checkpoint, pending work, and worker association. */
		async cleanupSource(sourceId) {
			const normalizedId = requiredText(sourceId, "sourceId");
			return withLock(directoryFor(normalizedId), async () => {
				const directory = directoryFor(normalizedId);
				try {
					await fs.rm(directory, { recursive: true, force: false });
					return true;
				} catch (error) {
					if (error.code === "ENOENT") return false;
					throw error;
				}
			});
		},
	};
}
