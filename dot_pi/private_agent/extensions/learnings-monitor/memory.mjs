import { createHash } from "node:crypto";

const DEFAULT_BANKS = Object.freeze({
	personal: "cartwmic",
	"axon-work-computer": "work",
});
const DEFAULT_API_URL = "https://hindsight-api.internal.cartwmic.com";
const MAX_QUERY_CHARS = 800;
const MAX_SUMMARY_CHARS = 240;
const MAX_TIMEOUT_MS = 30_000;
const MAX_RESULTS = 10;
const MAX_PROMOTION_CHARS = 8_000;

function requiredText(value, name) {
	if (typeof value !== "string" || value.trim() === "") throw new TypeError(`${name} must be non-empty text`);
	return value.trim();
}

function configuredLimit(value, fallback, maximum) {
	if (!Number.isFinite(value) || value < 1) return fallback;
	return Math.min(Math.floor(value), maximum);
}

/** Resolve only known desktop profiles so a typo cannot silently select another bank. */
export function resolveMemoryBank(profile, bankIds = DEFAULT_BANKS) {
	const name = requiredText(profile, "profile");
	const bankId = bankIds?.[name];
	if (typeof bankId !== "string" || bankId.trim() === "") {
		throw new RangeError(`no Hindsight bank is configured for profile ${name}`);
	}
	return bankId.trim();
}

function responseError(kind) {
	return { status: "failed", evidence: [], error: { kind } };
}

function fallbackMemoryId(text) {
	return createHash("sha256").update(text).digest("hex").slice(0, 24);
}

function normalizeRelated(response, bankId, maxResults) {
	if (!response || typeof response !== "object" || Array.isArray(response)) {
		return { ok: false };
	}
	const results = Array.isArray(response.results) ? response.results : [];
	const evidence = [];
	const seen = new Set();
	for (const item of results) {
		if (!item || typeof item !== "object" || typeof item.text !== "string" || item.text.trim() === "") continue;
		const text = item.text.trim();
		const memoryId = typeof item.id === "string" && item.id.trim() ? item.id.trim() : fallbackMemoryId(text);
		const id = `hindsight:${bankId}:${memoryId}`;
		if (seen.has(id)) continue;
		seen.add(id);
		evidence.push({
			id,
			sourceLabel: `Hindsight bank: ${bankId}`,
			summary: text.slice(0, MAX_SUMMARY_CHARS),
			...(typeof item.id === "string" && item.id.trim()
				? { sourcePointer: `hindsight://banks/${encodeURIComponent(bankId)}/memories/${encodeURIComponent(memoryId)}` }
				: {}),
			classification: "possible-analogue",
			verifiedOccurrence: false,
		});
		if (evidence.length >= maxResults) break;
	}
	return { ok: true, evidence };
}

/**
 * Create an optional Hindsight adapter. Related lookups return source-neutral
 * analogues and failures as data; callers can persist local work independently.
 */
export function createHindsightMemoryAdapter({
	profile,
	bankIds = DEFAULT_BANKS,
	apiUrl = DEFAULT_API_URL,
	apiToken = "",
	requestTimeoutMs = 1_500,
	maxQueryChars = MAX_QUERY_CHARS,
	maxResults = 5,
	recallTypes = ["observation"],
	recallBudget = "low",
	recallMaxTokens = 512,
} = {}) {
	const bankId = resolveMemoryBank(profile, bankIds);
	const baseUrl = requiredText(apiUrl, "apiUrl").replace(/\/+$/, "");
	let parsedBase;
	try {
		parsedBase = new URL(baseUrl);
	} catch {
		throw new TypeError("apiUrl must be an absolute HTTP(S) URL");
	}
	if (parsedBase.protocol !== "http:" && parsedBase.protocol !== "https:") {
		throw new TypeError("apiUrl must use HTTP or HTTPS");
	}
	if (typeof apiToken !== "string") throw new TypeError("apiToken must be a string");
	if (!Array.isArray(recallTypes) || !recallTypes.every((item) => typeof item === "string")) {
		throw new TypeError("recallTypes must be an array of strings");
	}
	if (!["low", "mid", "high"].includes(recallBudget)) throw new TypeError("recallBudget must be low, mid, or high");
	const timeoutMs = configuredLimit(requestTimeoutMs, 1_500, MAX_TIMEOUT_MS);
	const queryLimit = configuredLimit(maxQueryChars, MAX_QUERY_CHARS, MAX_QUERY_CHARS);
	const resultLimit = configuredLimit(maxResults, 5, MAX_RESULTS);
	const tokenLimit = configuredLimit(recallMaxTokens, 512, 4_096);
	const sourceLabel = `Hindsight bank: ${bankId}`;
	const previews = new WeakMap();
	const confirmations = new WeakMap();

	const endpoint = (resource) => `${baseUrl}/v1/default/banks/${encodeURIComponent(bankId)}/memories${resource ? `/${resource}` : ""}`;

	async function postJson(resource, body, { parseResponse = false } = {}) {
		const controller = new AbortController();
		let timedOut = false;
		const timer = setTimeout(() => {
			timedOut = true;
			controller.abort();
		}, timeoutMs);
		timer.unref?.();
		try {
			const headers = { "Content-Type": "application/json", Accept: "application/json" };
			if (apiToken) headers.Authorization = `Bearer ${apiToken}`;
			const response = await fetch(endpoint(resource), {
				method: "POST",
				headers,
				body: JSON.stringify(body),
				signal: controller.signal,
			});
			if (!response.ok) {
				response.body?.cancel().catch(() => {});
				return { ok: false, kind: "http-error" };
			}
			if (!parseResponse) return { ok: true };
			try {
				return { ok: true, value: await response.json() };
			} catch {
				return { ok: false, kind: "invalid-response" };
			}
		} catch {
			return { ok: false, kind: timedOut ? "timeout" : "request-error" };
		} finally {
			clearTimeout(timer);
		}
	}

	async function related(query) {
		if (typeof query !== "string") throw new TypeError("query must be text");
		const boundedQuery = query.trim().slice(0, queryLimit);
		if (!boundedQuery) return { status: "empty", evidence: [] };
		const request = await postJson("recall", {
			query: boundedQuery,
			types: recallTypes,
			budget: recallBudget,
			max_tokens: tokenLimit,
		}, { parseResponse: true });
		if (!request.ok) return responseError(request.kind);
		try {
			const normalized = normalizeRelated(request.value, bankId, resultLimit);
			if (!normalized.ok) return responseError("invalid-response");
			return {
				status: normalized.evidence.length ? "found" : "empty",
				evidence: normalized.evidence,
			};
		} catch {
			return responseError("invalid-response");
		}
	}

	function previewPromotion(record, exactText) {
		if (!record || typeof record !== "object" || Array.isArray(record)) throw new TypeError("record must be an object");
		if (record.status !== "kept") throw new Error("only a kept opportunity can be promoted");
		const observation = requiredText(record.observation, "record.observation");
		const recommendation = typeof record.recommendation === "string" ? record.recommendation.trim() : "";
		const text = exactText === undefined
			? [observation, recommendation].filter(Boolean).join("\n\n")
			: exactText;
		if (typeof text !== "string" || text.trim() === "") throw new TypeError("promotion text must be non-empty text");
		if (text.length > MAX_PROMOTION_CHARS) throw new RangeError(`promotion text must be at most ${MAX_PROMOTION_CHARS} characters`);
		const preview = Object.freeze({ text, bankId, sourceLabel });
		previews.set(preview, text);
		return preview;
	}

	/** Mark the displayed preview as confirmed. Passing false creates no request payload. */
	function confirmPromotion(preview, confirmed) {
		if (!preview || typeof preview !== "object" || !previews.has(preview)) {
			throw new TypeError("preview must come from this adapter");
		}
		if (confirmed !== true) return null;
		const payload = Object.freeze({ confirmed: true });
		confirmations.set(payload, previews.get(preview));
		return payload;
	}

	/** Send only a one-use confirmed preview; a 2xx response means accepted, not searchable. */
	async function retainConfirmed(payload) {
		if (payload === null || payload === undefined) return { status: "cancelled" };
		const text = payload && typeof payload === "object" ? confirmations.get(payload) : undefined;
		if (text === undefined) return { status: "rejected", reason: "not-confirmed" };
		confirmations.delete(payload);
		const request = await postJson("", { items: [{ content: text }], async: true });
		if (!request.ok) return { status: "failed", error: { kind: request.kind } };
		return {
			status: "accepted",
			bankId,
			message: "Hindsight accepted the asynchronous retain request; it may not be searchable yet.",
		};
	}

	return Object.freeze({
		profile,
		bankId,
		related,
		previewPromotion,
		confirmPromotion,
		retainConfirmed,
	});
}
