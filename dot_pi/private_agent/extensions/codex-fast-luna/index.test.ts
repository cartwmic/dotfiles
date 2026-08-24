import assert from "node:assert/strict";
import { test } from "node:test";
import {
	FAST_SERVICE_TIER,
	LUNA_MODEL,
	LUNA_MODEL_ID,
	LUNA_PROVIDER,
	applyFastTier,
	isLunaModel,
	payloadLooksLikeLuna,
	shouldFast,
} from "./index.ts";

test("isLunaModel: only openai-codex/gpt-5.6-luna", () => {
	assert.equal(isLunaModel({ provider: LUNA_PROVIDER, id: LUNA_MODEL_ID }), true);
	assert.equal(isLunaModel({ provider: LUNA_PROVIDER, id: "gpt-5.6-sol" }), false);
	assert.equal(isLunaModel({ provider: LUNA_PROVIDER, id: "gpt-5.6-terra" }), false);
	assert.equal(isLunaModel({ provider: "cursor", id: LUNA_MODEL_ID }), false);
	assert.equal(isLunaModel(undefined), false);
});

test("payloadLooksLikeLuna: id or provider/id, ignores missing model", () => {
	assert.equal(payloadLooksLikeLuna({ model: LUNA_MODEL_ID }), true);
	assert.equal(payloadLooksLikeLuna({ model: LUNA_MODEL }), true);
	assert.equal(payloadLooksLikeLuna({ model: "gpt-5.6-sol" }), false);
	assert.equal(payloadLooksLikeLuna({ model: null }), false);
	assert.equal(payloadLooksLikeLuna(null), false);
});

test("shouldFast: ctx model or payload model is enough", () => {
	assert.equal(shouldFast({ provider: LUNA_PROVIDER, id: LUNA_MODEL_ID }, { model: null }), true);
	assert.equal(shouldFast({ provider: LUNA_PROVIDER, id: "gpt-5.6-sol" }, { model: LUNA_MODEL_ID }), true);
	assert.equal(shouldFast({ provider: LUNA_PROVIDER, id: "gpt-5.6-sol" }, { model: "gpt-5.6-sol" }), false);
});

test("applyFastTier: sets priority and preserves the rest", () => {
	const patched = applyFastTier({ model: LUNA_MODEL_ID, stream: true }) as Record<string, unknown>;
	assert.equal(patched.service_tier, FAST_SERVICE_TIER);
	assert.equal(patched.model, LUNA_MODEL_ID);
	assert.equal(patched.stream, true);
	assert.equal(applyFastTier(null), null);
	assert.deepEqual(applyFastTier(["x"]), ["x"]);
});
