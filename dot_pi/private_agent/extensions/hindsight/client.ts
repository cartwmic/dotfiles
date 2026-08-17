/**
 * Minimal Hindsight REST client (node stdlib only). Talks to the bank's
 * recall + retain endpoints. All calls are best-effort: on any failure they
 * throw, and the caller no-ops so a memory hiccup never blocks a pi turn.
 */
import * as https from "node:https";
import * as http from "node:http";
import { URL } from "node:url";
import type { HindsightConfig } from "./config.ts";
import type { RecallResultLite } from "./content.ts";

export interface MemoryItemInput {
	content: string;
	tags?: string[];
	context?: string;
	document_id?: string;
	update_mode?: "replace" | "append";
	timestamp?: string;
}

function bankBase(cfg: HindsightConfig): string {
	return `${cfg.apiUrl}/v1/default/banks/${encodeURIComponent(cfg.bankId)}`;
}

/** POST JSON to an absolute URL with timeout + optional bearer. Resolves parsed JSON. */
export function postJson(
	cfg: HindsightConfig,
	url: string,
	body: unknown,
): Promise<unknown> {
	return new Promise((resolve, reject) => {
		let payload: string;
		try {
			payload = JSON.stringify(body);
		} catch (e) {
			reject(e);
			return;
		}
		const u = new URL(url);
		const transport = u.protocol === "http:" ? http : https;
		const headers: Record<string, string> = {
			"Content-Type": "application/json",
			"Content-Length": String(Buffer.byteLength(payload)),
			Accept: "application/json",
		};
		if (cfg.apiToken) headers.Authorization = `Bearer ${cfg.apiToken}`;

		const req = transport.request(
			u,
			{ method: "POST", headers, timeout: cfg.requestTimeoutMs },
			(res) => {
				const chunks: Buffer[] = [];
				res.on("data", (c) => chunks.push(c as Buffer));
				res.on("end", () => {
					const text = Buffer.concat(chunks).toString("utf8");
					const status = res.statusCode ?? 0;
					if (status < 200 || status >= 300) {
						reject(new Error(`HTTP ${status}: ${text.slice(0, 200)}`));
						return;
					}
					try {
						resolve(text ? JSON.parse(text) : {});
					} catch (e) {
						reject(e);
					}
				});
			},
		);
		req.on("error", reject);
		req.on("timeout", () => req.destroy(new Error("request timed out")));
		req.write(payload);
		req.end();
	});
}

/** Recall memories for a query. Returns a trimmed result list (possibly empty). */
export async function recall(
	cfg: HindsightConfig,
	query: string,
): Promise<RecallResultLite[]> {
	const resp = (await postJson(cfg, `${bankBase(cfg)}/memories/recall`, {
		query,
		types: cfg.recallTypes,
		budget: cfg.recallBudget,
		max_tokens: cfg.recallMaxTokens,
	})) as { results?: Array<Record<string, unknown>> };
	const results = Array.isArray(resp?.results) ? resp.results : [];
	return results
		.map((r) => ({
			id: String(r.id ?? ""),
			text: String(r.text ?? ""),
			type: (r.type as string | null) ?? null,
		}))
		.filter((r) => r.text.length > 0);
}

/** Retain items into the bank. Async extraction (non-blocking server-side). */
export async function retain(
	cfg: HindsightConfig,
	items: MemoryItemInput[],
	documentTags?: string[],
): Promise<void> {
	await postJson(cfg, `${bankBase(cfg)}/memories`, {
		items,
		async: true,
		...(documentTags && documentTags.length ? { document_tags: documentTags } : {}),
	});
}
