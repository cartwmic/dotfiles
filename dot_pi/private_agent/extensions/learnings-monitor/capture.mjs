import { createHash } from "node:crypto";

export const OBSERVER_SESSION_MARKER = "learnings-monitor-observer";
export const DEFAULT_BATCH_THRESHOLD = 3;
export const MAX_BATCH_EVIDENCE = 8;
export const MAX_USER_CHARS = 1200;
export const MAX_ASSISTANT_CHARS = 1600;
export const MAX_TOOL_ACTIONS = 8;
export const MAX_TOOL_EXCERPT_CHARS = 180;
export const MAX_EXCHANGE_CHARS = 4200;
export const MAX_BATCH_BYTES = 160 * 1024;

const CURSOR_VERSION = 1;
const SECRET_PATTERNS = [
	/(\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|token|password|passwd|secret)\b\s*[:=]\s*)([^\s,;]+)/gi,
	/\b(Bearer\s+)[A-Za-z0-9._~+/-]+=*/gi,
	/\b(sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16})\b/g,
	/-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/g,
	/([?&](?:token|key|password|secret|code)=)[^&#\s]*/gi,
];

function hash(value, length = 32) {
	return createHash("sha256").update(String(value)).digest("hex").slice(0, length);
}

function textOf(content) {
	if (typeof content === "string") return content;
	if (!Array.isArray(content)) return "";
	return content.filter((item) => item?.type === "text" && typeof item.text === "string").map((item) => item.text).join("\n");
}

/** Redact common credential shapes, home-directory names, and email addresses before truncating. */
export function privacyFilter(value, maxLength = MAX_EXCHANGE_CHARS) {
	let text = String(value ?? "");
	for (const pattern of SECRET_PATTERNS) text = text.replace(pattern, (_match, prefix) => prefix ? `${prefix}[redacted]` : "[redacted]");
	text = text
		.replace(/([a-z][a-z0-9+.-]*:\/\/)[^/@\s]+@/gi, "$1[redacted]@")
		.replace(/(?:\/Users\/|\/home\/)[^/\s]+/g, "~/[user]")
		.replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, "[email]")
		.replace(/\u0000/g, "")
		.replace(/[ \t]+/g, " ")
		.trim();
	return text.length > maxLength ? `${text.slice(0, Math.max(0, maxLength - 1))}…` : text;
}

function timestampOf(entry) {
	const messageTime = entry?.message?.timestamp;
	if (Number.isFinite(messageTime)) return messageTime;
	const time = Date.parse(entry?.timestamp ?? "");
	return Number.isFinite(time) ? time : 0;
}

function messageOf(entry) {
	return entry?.type === "message" ? entry.message : undefined;
}

function outcomeFor(entries, terminalMessage) {
	const assistantReasons = entries.map((entry) => messageOf(entry)).filter((message) => message?.role === "assistant").map((message) => message.stopReason);
	if (assistantReasons.some((reason) => ["aborted", "deferred", "length"].includes(reason))) return "incomplete";
	if (terminalMessage?.stopReason === "toolUse") return "incomplete";
	if (assistantReasons.includes("error")) return "failed";
	for (const entry of entries) {
		const message = messageOf(entry);
		if (message?.role === "toolResult" && message.isError) return "failed";
		if (message?.role === "bashExecution" && (message.cancelled || (Number.isFinite(message.exitCode) && message.exitCode !== 0))) return message.cancelled ? "incomplete" : "failed";
	}
	return "completed";
}

function summarizeToolActions(entries) {
	const results = new Map();
	for (const entry of entries) {
		const message = messageOf(entry);
		if (message?.role === "toolResult" && typeof message.toolCallId === "string") results.set(message.toolCallId, message);
	}
	const actions = [];
	for (const entry of entries) {
		const message = messageOf(entry);
		if (message?.role === "assistant" && Array.isArray(message.content)) {
			for (const block of message.content) {
				if (block?.type !== "toolCall") continue;
				const result = results.get(block.id);
				const outcome = !result ? "incomplete" : result.isError ? "failed" : "completed";
				const name = /^[a-zA-Z0-9_-]{1,48}$/.test(block.name ?? "") ? block.name : "tool";
				const excerpt = result ? privacyFilter(textOf(result.content), MAX_TOOL_EXCERPT_CHARS) : "";
				actions.push({ name, outcome, ...(excerpt ? { excerpt } : {}) });
				if (actions.length >= MAX_TOOL_ACTIONS) return actions;
			}
		} else if (message?.role === "bashExecution") {
			const outcome = message.cancelled ? "incomplete" : message.exitCode === 0 ? "completed" : "failed";
			const excerpt = privacyFilter(message.output ?? "", MAX_TOOL_EXCERPT_CHARS);
			actions.push({ name: "direct-command", outcome, ...(excerpt ? { excerpt } : {}) });
			if (actions.length >= MAX_TOOL_ACTIONS) return actions;
		}
	}
	return actions;
}

function settledExchangeEntries(entries, terminalMessage) {
	const terminalIndex = entries.findIndex((entry) => messageOf(entry) === terminalMessage);
	if (terminalIndex < 0) return entries;
	let start = 0;
	for (let index = terminalIndex; index >= 0; index--) {
		if (messageOf(entries[index])?.role === "user") {
			start = index;
			break;
		}
	}
	return entries.slice(start, terminalIndex + 1);
}

function makeEvidence({ sourceId, sessionId, terminalEntry, exchangeEntries, branch }) {
	const terminalMessage = messageOf(terminalEntry);
	const evidenceId = `pi-ev-${hash(`${sourceId}\0${terminalEntry.id}`)}`;
	const userText = privacyFilter(
		exchangeEntries.map((entry) => messageOf(entry)).filter((message) => message?.role === "user").map((message) => textOf(message.content)).join("\n"),
		MAX_USER_CHARS,
	);
	const assistantText = privacyFilter(
		exchangeEntries.map((entry) => messageOf(entry)).filter((message) => message?.role === "assistant").map((message) => textOf(message.content)).filter(Boolean).join("\n"),
		MAX_ASSISTANT_CHARS,
	);
	const actions = summarizeToolActions(exchangeEntries);
	const outcome = outcomeFor(exchangeEntries, terminalMessage);
	const parts = [];
	if (userText) parts.push(`User: ${userText}`);
	for (const action of actions) {
		parts.push(`Tool ${action.name} — ${action.outcome}${action.excerpt ? `; excerpt: ${action.excerpt}` : ""}`);
	}
	for (const message of exchangeEntries.map((entry) => messageOf(entry))) {
		if (message?.role === "assistant" && message.stopReason === "error" && message.errorMessage) {
			parts.push(`Attempt error: ${privacyFilter(message.errorMessage, 240)}`);
		}
	}
	if (assistantText) parts.push(`Assistant: ${assistantText}`);
	const summary = privacyFilter(parts.join("\n"), MAX_EXCHANGE_CHARS) || `Settled Pi exchange (${outcome}).`;
	const pointer = `pi-session://${encodeURIComponent(sessionId)}#${encodeURIComponent(terminalEntry.id)}`;
	const occurredAt = timestampOf(terminalEntry);
	return {
		id: evidenceId,
		summary,
		outcome,
		...(occurredAt > 0 ? { occurredAt: new Date(occurredAt).toISOString() } : {}),
		provenance: { pointer, availability: "available", context: branch },
	};
}

function cursorValue(value) {
	if (!value || typeof value !== "object" || Array.isArray(value) || value.version !== CURSOR_VERSION) {
		return { version: CURSOR_VERSION, enabledAt: 0, seenEvidenceIds: [], lastLeafId: null };
	}
	return {
		version: CURSOR_VERSION,
		enabledAt: Number.isFinite(value.enabledAt) ? value.enabledAt : 0,
		seenEvidenceIds: [...new Set(Array.isArray(value.seenEvidenceIds) ? value.seenEvidenceIds.filter((id) => typeof id === "string") : [])],
		lastLeafId: typeof value.lastLeafId === "string" ? value.lastLeafId : null,
	};
}

function pendingEvidenceIds(pending) {
	const ids = [];
	for (const batch of pending ?? []) {
		const evidence = batch?.payload?.evidence;
		if (Array.isArray(evidence)) for (const item of evidence) if (typeof item?.id === "string") ids.push(item.id);
	}
	return ids;
}

function persisted(sessionManager) {
	if (typeof sessionManager?.isPersisted === "function") return sessionManager.isPersisted();
	return typeof sessionManager?.getSessionFile === "function" && Boolean(sessionManager.getSessionFile());
}

function modelSnapshot(ctx) {
	const model = ctx?.model;
	return typeof model?.provider === "string" && typeof model?.id === "string"
		? { provider: model.provider, id: model.id }
		: null;
}

export function isObserverSession(sessionManager) {
	if (typeof sessionManager?.getEntries !== "function") return false;
	return sessionManager.getEntries().some((entry) =>
		(entry?.type === "custom" || entry?.type === "custom_message") && entry.customType === OBSERVER_SESSION_MARKER,
	);
}

export function piSourceId(sessionId) {
	if (typeof sessionId !== "string" || sessionId.length === 0) throw new TypeError("sessionId must be non-empty text");
	return `pi-source-${hash(sessionId, 48)}`;
}

export function piBranchContext(sessionManager) {
	const branch = typeof sessionManager?.getBranch === "function" ? sessionManager.getBranch() : [];
	const entries = typeof sessionManager?.getEntries === "function" ? sessionManager.getEntries() : branch;
	const children = new Map();
	for (const entry of entries) {
		if (typeof entry?.parentId !== "string") continue;
		if (!children.has(entry.parentId)) children.set(entry.parentId, []);
		children.get(entry.parentId).push(entry.id);
	}
	const choices = [];
	for (let index = 0; index + 1 < branch.length; index++) {
		const parent = branch[index];
		const child = branch[index + 1];
		const siblings = children.get(parent.id) ?? [];
		if (siblings.length > 1) choices.push(child.id);
	}
	return choices.length ? `branch:${hash(choices.join("\0"), 16)}` : "branch:main";
}

function latestSettledAssistant(branch) {
	for (let index = branch.length - 1; index >= 0; index--) {
		const message = messageOf(branch[index]);
		if (message?.role === "assistant" && message.stopReason !== "pending") return branch[index];
	}
	return undefined;
}

function isAfterCheckpoint(branch, cursor, entry) {
	const entryIndex = branch.findIndex((item) => item.id === entry.id);
	const checkpointIndex = cursor.lastLeafId ? branch.findIndex((item) => item.id === cursor.lastLeafId) : -1;
	if (checkpointIndex >= 0) return entryIndex > checkpointIndex;
	return timestampOf(entry) >= cursor.enabledAt;
}

function createCursorAfter(currentCursor, evidence, leafId, knownEvidenceIds) {
	return {
		version: CURSOR_VERSION,
		enabledAt: currentCursor.enabledAt,
		seenEvidenceIds: [...new Set([...currentCursor.seenEvidenceIds, ...knownEvidenceIds, evidence.id])],
		lastLeafId: leafId ?? currentCursor.lastLeafId,
	};
}

function activityPayload(sourceId, sourceLabel, evidence) {
	return { source: { id: sourceId, label: sourceLabel }, evidence: [evidence] };
}

function mergeActivityPayloads(batches) {
	const first = batches[0]?.payload;
	return {
		source: first.source,
		evidence: batches.flatMap((batch) => batch.payload.evidence),
	};
}

function storedBatchId(sourceId, evidenceId) {
	return `pi-pending-${hash(`${sourceId}\0${evidenceId}`)}`;
}

function boundedScheduledBatch(sourceId, batches, cwd) {
	const activity = mergeActivityPayloads(batches);
	const serialized = JSON.stringify(activity);
	if (Buffer.byteLength(serialized, "utf8") > MAX_BATCH_BYTES) throw new Error("serialized Pi activity batch exceeded 160 KiB");
	return {
		sourceId,
		cwd,
		batchId: `pi-batch-${hash(batches.map((batch) => batch.id).join("\0"))}`,
		pendingBatchIds: batches.map((batch) => batch.id),
		payload: activity,
	};
}

/**
 * Capture bridge for persisted Pi primaries. scheduleBatch must resolve only
 * after the result has been durably accepted by the local record store; only
 * then does this bridge remove queue heads and advance the cursor. It receives
 * no ExtensionContext. A rejected/aborted call leaves the durable batch queued.
 * Captures only enqueue; threshold, resume/re-enable, and explicit flush request
 * detached drains. Requests arriving during a drain are coalesced and retried
 * after it releases the source lock, so crossing the threshold cannot be lost.
 * Explicit flush forces the queued work but never waits for the worker/model.
 */
export function createPiCaptureBridge({
	store,
	scheduleBatch = async () => { throw new Error("no durable activity-batch scheduler is connected"); },
	cancelWorker = async () => {},
	batchThreshold = DEFAULT_BATCH_THRESHOLD,
	maxBatchEvidence = MAX_BATCH_EVIDENCE,
	now = Date.now,
	onError = () => {},
} = {}) {
	if (!store) throw new TypeError("store is required");
	if (!Number.isInteger(batchThreshold) || batchThreshold < 1) throw new TypeError("batchThreshold must be a positive integer");
	if (!Number.isInteger(maxBatchEvidence) || maxBatchEvidence < 1 || maxBatchEvidence > MAX_BATCH_EVIDENCE) {
		throw new TypeError(`maxBatchEvidence must be between 1 and ${MAX_BATCH_EVIDENCE}`);
	}
	const disabledSources = new Set();
	const drainingSources = new Set();
	const requestedDrains = new Map();
	const sourceOf = (ctx) => piSourceId(ctx.sessionManager.getSessionId());
	const sourceLabel = (sourceId) => `Pi session ${sourceId.slice(-8)}`;
	const reportError = (error, sourceId) => {
		try { onError(error, sourceId); } catch { /* observer diagnostics must not affect the primary */ }
	};

	async function refreshCursorBoundary(sourceId) {
		try {
			const state = await store.getOperationalState(sourceId);
			if (!state.enabled || state.pending.length) return;
			const cursor = cursorValue(state.cursor);
			const boundary = Math.max(cursor.enabledAt, now());
			if (boundary === cursor.enabledAt) return;
			cursor.enabledAt = boundary;
			await store.updateOperationalState(sourceId, { cursor });
		} catch (error) {
			reportError(error, sourceId);
		}
	}

	async function shutdownSource(sourceId) {
		try { await cancelWorker(sourceId); } catch (error) { reportError(error, sourceId); }
		return { ok: true, sourceId, pendingCount: (await store.getOperationalState(sourceId)).pending.length };
	}

	async function drain(sourceId, { force = false, explicit = false, primaryModel = null, cwd = process.cwd() } = {}) {
		if (drainingSources.has(sourceId)) {
			const previous = requestedDrains.get(sourceId);
			requestedDrains.set(sourceId, {
				force: force || previous?.force || false,
				explicit: explicit || previous?.explicit || false,
				primaryModel,
				cwd,
			});
			return;
		}
		drainingSources.add(sourceId);
		let completedQueue = false;
		try {
			let forceNext = force;
			while (true) {
				const state = await store.getOperationalState(sourceId);
				if ((!explicit && disabledSources.has(sourceId)) || (!state.enabled && !explicit)) return;
				const pending = state.pending ?? [];
				if (!pending.length) {
					completedQueue = true;
					return;
				}
				if (!forceNext && pending.length < batchThreshold) return;
				const selected = pending.slice(0, Math.min(maxBatchEvidence, pending.length));
				const batch = boundedScheduledBatch(sourceId, selected, cwd);
				await scheduleBatch({ ...batch, explicit, focus: state.focus ?? null, modelOverride: state.modelOverride ?? null, primaryModel });
				for (const id of batch.pendingBatchIds) await store.completePending(sourceId, id);
			}
		} catch (error) {
			reportError(error, sourceId);
		} finally {
			if (completedQueue) await refreshCursorBoundary(sourceId);
			drainingSources.delete(sourceId);
			const requested = requestedDrains.get(sourceId);
			if (requested) {
				requestedDrains.delete(sourceId);
				void drain(sourceId, requested).catch((error) => reportError(error, sourceId));
			}
		}
	}

	function readSource(ctx) {
		const sessionManager = ctx?.sessionManager;
		if (!sessionManager || !persisted(sessionManager)) return { ok: false, reason: "ephemeral" };
		if (isObserverSession(sessionManager)) return { ok: false, reason: "observer" };
		const sourceId = sourceOf(ctx);
		const cwd = typeof ctx.cwd === "string" ? ctx.cwd : sessionManager.getCwd?.() ?? process.cwd();
		return { ok: true, sourceId, label: sourceLabel(sourceId), sessionManager, cwd };
	}

	async function captureSettled(ctx) {
		const primaryModel = modelSnapshot(ctx);
		const source = readSource(ctx);
		if (!source.ok) return source;
		const state = await store.getOperationalState(source.sourceId);
		if (!state.enabled || disabledSources.has(source.sourceId)) return { ok: true, captured: false, reason: "off" };
		const cursor = cursorValue(state.cursor);
		const branch = source.sessionManager.getBranch();
		const terminalEntry = latestSettledAssistant(branch);
		if (!terminalEntry?.id) return { ok: true, captured: false, reason: "no-final-assistant" };
		const evidence = makeEvidence({
			sourceId: source.sourceId,
			sessionId: source.sessionManager.getSessionId(),
			terminalEntry,
			exchangeEntries: settledExchangeEntries(branch, messageOf(terminalEntry)),
			branch: piBranchContext(source.sessionManager),
		});
		if (!isAfterCheckpoint(branch, cursor, terminalEntry)) return { ok: true, captured: false, reason: "before-enable" };
		const alreadyKnown = new Set([...cursor.seenEvidenceIds, ...pendingEvidenceIds(state.pending)]);
		if (alreadyKnown.has(evidence.id)) return { ok: true, captured: false, reason: "already-seen" };
		const leafId = source.sessionManager.getLeafId?.() ?? terminalEntry.id;
		const cursorAfter = createCursorAfter(cursor, evidence, leafId, alreadyKnown);
		const batch = { id: storedBatchId(source.sourceId, evidence.id), payload: activityPayload(source.sourceId, source.label, evidence), cursorAfter };
		const updated = await store.enqueuePending(source.sourceId, batch);
		if (updated.enabled && updated.pending.length >= batchThreshold && !disabledSources.has(source.sourceId)) {
			void drain(source.sourceId, { primaryModel, cwd: source.cwd }).catch((error) => reportError(error, source.sourceId));
		}
		return { ok: true, captured: true, evidenceId: evidence.id, pendingCount: updated.pending.length };
	}

	return {
		async enable(ctx) {
			const primaryModel = modelSnapshot(ctx);
			const source = readSource(ctx);
			if (!source.ok) return source;
			disabledSources.delete(source.sourceId);
			const state = await store.getOperationalState(source.sourceId);
			if (state.enabled) {
				if (state.pending.length) void drain(source.sourceId, { force: true, primaryModel, cwd: source.cwd }).catch((error) => reportError(error, source.sourceId));
				return { ok: true, sourceId: source.sourceId, state };
			}
			const prior = cursorValue(state.cursor);
			const pendingIds = pendingEvidenceIds(state.pending);
			const cursor = {
				version: CURSOR_VERSION,
				enabledAt: now(),
				seenEvidenceIds: [...new Set([...prior.seenEvidenceIds, ...pendingIds])],
				lastLeafId: source.sessionManager.getLeafId?.() ?? null,
			};
			const updated = await store.updateOperationalState(source.sourceId, { enabled: true, cursor });
			if (updated.pending.length) void drain(source.sourceId, { force: true, primaryModel, cwd: source.cwd }).catch((error) => reportError(error, source.sourceId));
			return { ok: true, sourceId: source.sourceId, state: updated };
		},

		async disable(ctx) {
			if (ctx?.sessionManager?.getSessionId) disabledSources.add(sourceOf(ctx));
			const source = readSource(ctx);
			if (!source.ok) return source;
			disabledSources.add(source.sourceId);
			const state = await store.updateOperationalState(source.sourceId, { enabled: false });
			try { await cancelWorker(source.sourceId); } catch (error) { reportError(error, source.sourceId); }
			return { ok: true, sourceId: source.sourceId, state };
		},

		async status(ctx) {
			const source = readSource(ctx);
			if (!source.ok) return source;
			const state = await store.getOperationalState(source.sourceId);
			return {
				ok: true,
				sourceId: source.sourceId,
				enabled: state.enabled,
				pendingCount: state.pending.length,
				pendingEvidenceCount: state.pending.reduce((count, batch) => count + (batch.payload?.evidence?.length ?? 0), 0),
				branch: piBranchContext(source.sessionManager),
				state,
			};
		},

		async flush(ctx) {
			const primaryModel = modelSnapshot(ctx);
			const source = readSource(ctx);
			if (!source.ok) return source;
			const state = await store.getOperationalState(source.sourceId);
			if (!state.pending.length) return { ok: true, sourceId: source.sourceId, scheduled: false, pendingCount: 0 };
			void drain(source.sourceId, { force: true, explicit: true, primaryModel, cwd: source.cwd }).catch((error) => reportError(error, source.sourceId));
			return { ok: true, sourceId: source.sourceId, scheduled: true, pendingCount: state.pending.length };
		},

		async resume(ctx) {
			const primaryModel = modelSnapshot(ctx);
			const source = readSource(ctx);
			if (!source.ok) return source;
			const state = await store.getOperationalState(source.sourceId);
			let pendingCount = state.pending.length;
			if (state.enabled) {
				disabledSources.delete(source.sourceId);
				// The last finalized assistant may have been saved before agent_settled ran.
				// Queue it against the saved cursor; never advance that boundary first.
				await captureSettled(ctx);
				pendingCount = (await store.getOperationalState(source.sourceId)).pending.length;
				if (pendingCount) void drain(source.sourceId, { force: true, primaryModel, cwd: source.cwd }).catch((error) => reportError(error, source.sourceId));
			} else {
				disabledSources.add(source.sourceId);
			}
			return { ok: true, sourceId: source.sourceId, enabled: state.enabled, pendingCount };
		},

		captureSettled,

		async treeChanged(ctx) {
			const source = readSource(ctx);
			if (!source.ok) return source;
			return { ok: true, sourceId: source.sourceId, branch: piBranchContext(source.sessionManager) };
		},

		shutdown(ctx) {
			const source = readSource(ctx);
			if (!source.ok) return Promise.resolve(source);
			disabledSources.add(source.sourceId);
			return shutdownSource(source.sourceId);
		},
	};
}

/** Register lifecycle hooks. Each callback passes its current context through and retains no context. */
export function registerPiCaptureLifecycle(pi, bridge) {
	pi.on("session_start", async (_event, ctx) => {
		try { return await bridge.resume(ctx); } catch (error) { /* do not interrupt primary startup */ }
	});
	pi.on("agent_settled", async (_event, ctx) => {
		try { return await bridge.captureSettled(ctx); } catch (error) { /* do not interrupt primary work */ }
	});
	pi.on("session_tree", async (_event, ctx) => {
		try { return await bridge.treeChanged(ctx); } catch (error) { /* branch navigation must remain available */ }
	});
	pi.on("session_shutdown", (_event, ctx) => {
		void bridge.shutdown(ctx).catch(() => {});
	});
}
