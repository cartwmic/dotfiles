// Pure budget policy. Kept out of backend.mjs: the detached backend process runs
// from this directory, whose index.ts is auto-loaded by its own resource loader and
// imports this file. Importing backend.mjs from index.ts deadlocked (Node exit 13).
export class LimitFailure extends Error {
  constructor(reason, message) { super(message); this.reason = reason; }
}
/** SDK estimates are not a tokenizer. The generic byte transport ceiling is
 * derived from the captured prompt's measured bytes/estimated tokens, not a Pi
 * application cap. Every actual routed call is independently estimated below.
 * Reserve the system prompt, serialized request framing and effective output;
 * reasoning adapters may consume the entire model output ceiling.
 */
export function budgets(model, selection, thinkingLevel, estimateTokens, input) {
  const context = model.contextWindow, limit = model.maxTokens;
  const requested = selection.options.maxTokens ?? limit;
  if (![context, limit, requested].every(n => Number.isSafeInteger(n) && n > 0)) throw new LimitFailure('model_limits', 'Recap model limits unavailable');
  const maxTokens = Math.min(requested, limit, Math.floor(context / 4));
  const outputReserve = thinkingLevel === 'off' ? maxTokens : limit;
  const framing = JSON.stringify({ systemPrompt: selection.instructions, messages: [{ role: 'user', content: [{ type: 'text', text: '' }] }] });
  const inputTokens = estimateTokens({ role: 'user', content: [{ type: 'text', text: input }] });
  const availableTokens = context - outputReserve - estimateTokens({ role: 'system', content: framing });
  if (availableTokens <= 0 || !Number.isSafeInteger(inputTokens) || inputTokens <= 0) throw new LimitFailure('model_limits', 'Recap model budget unusable');
  const inputBudget = Math.floor(Buffer.byteLength(input, 'utf8') * availableTokens / inputTokens);
  if (!Number.isSafeInteger(inputBudget) || inputBudget <= 0) throw new LimitFailure('model_limits', 'Recap model budget unusable');
  return { inputBudget, maxTokens, availableTokens, estimatedInputTokens: inputTokens };
}
