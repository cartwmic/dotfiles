/**
 * codex-fast-luna — always send Codex Fast (`service_tier: "priority"`)
 * for openai-codex/gpt-5.6-luna. Other models are left unchanged.
 *
 * Replaces the third-party pi-codex-fast package, which Fast-ifies every
 * supported Codex model once the toggle is on.
 */
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

export const LUNA_PROVIDER = "openai-codex";
export const LUNA_MODEL_ID = "gpt-5.6-luna";
export const LUNA_MODEL = `${LUNA_PROVIDER}/${LUNA_MODEL_ID}`;
export const FAST_SERVICE_TIER = "priority";
const STATUS_KEY = "codex-fast-luna";

export function isLunaModel(model: { provider?: string; id?: string } | undefined | null): boolean {
	return model?.provider === LUNA_PROVIDER && model?.id === LUNA_MODEL_ID;
}

export function payloadModelId(payload: unknown): string | undefined {
	if (!payload || typeof payload !== "object" || Array.isArray(payload)) return undefined;
	const model = (payload as { model?: unknown }).model;
	return typeof model === "string" ? model : undefined;
}

export function payloadLooksLikeLuna(payload: unknown): boolean {
	const model = payloadModelId(payload);
	return model === LUNA_MODEL_ID || model === LUNA_MODEL;
}

export function shouldFast(model: { provider?: string; id?: string } | undefined | null, payload: unknown): boolean {
	return isLunaModel(model) || payloadLooksLikeLuna(payload);
}

export function applyFastTier(payload: unknown): unknown {
	if (!payload || typeof payload !== "object" || Array.isArray(payload)) return payload;
	return { ...(payload as Record<string, unknown>), service_tier: FAST_SERVICE_TIER };
}

function refreshStatus(ctx: ExtensionContext): void {
	if (!ctx.hasUI) return;
	if (isLunaModel(ctx.model)) {
		ctx.ui.setStatus(STATUS_KEY, "Fast");
		return;
	}
	ctx.ui.setStatus(STATUS_KEY, undefined);
}

export default function (pi: ExtensionAPI): void {
	pi.on("session_start", (_event, ctx) => {
		refreshStatus(ctx);
	});

	pi.on("model_select", (_event, ctx) => {
		refreshStatus(ctx);
	});

	pi.on("before_provider_request", (event, ctx) => {
		if (!shouldFast(ctx.model, event.payload)) return;
		return applyFastTier(event.payload);
	});
}
