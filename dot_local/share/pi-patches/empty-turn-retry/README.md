# pi-patch: empty-turn-retry

Surfaces degenerate empty assistant turns as retryable provider errors inside
pi-ai's anthropic-messages stream function, so the agent loop auto-retries
instead of ending the turn silently.

## Problem

Gateway models sometimes sample EOS immediately. GLM-5.3 via
`litellm.boost-llm.dev` does this in two shapes (both verified in pi session
transcripts, 23 instances across recent sessions):

1. **Empty turn after a tool call.** The assistant emits a tool call, the tool
   executes, and the *next* model response is an empty text block with
   `rawStopReason: "end_turn"` and 0 output tokens. The turn ends as if it
   finished successfully; the user has to type "continue".
2. **Thinking-only turn.** The model burns the whole turn on reasoning (one
   observed instance: 62K chars of thinking) and emits no text or tool call,
   then `end_turn`.

pi's agent loop (pi-agent-core `drive/response.js`) continues whenever a
response contains tool-call blocks — regardless of stop reason. But a response
with *no* content and `end_turn` falls through to the checkpoint path and the
turn ends silently. No error is shown.

Example transcript shape (aar-forge session, 2026-09-10):

```
[1174] assistant sr=toolUse: toolCall(bash)
[1175] toolResult: 'exit=20 ...'
[1176] assistant sr=stop: text("") — rawStopReason=end_turn, output_tokens=0
[1177] user: 'continie'          <- user had to nudge it
```

Not a context overflow: the example above had ~695K tokens of headroom left in
the 1,048,576-token window. It is intermittent, which fits sampling noise
(likely aggravated by the NVFP4 quantization of the pinned GLM checkpoint).

## Fix

In `@earendil-works/pi-ai/dist/api/anthropic-messages.js` `stream()`, after the
existing terminal checks (`pending` / `aborted` / `error`), reject a
`stopReason === "stop"` turn whose content has **no tool-call block and no
non-empty text block** by throwing:

```
Provider returned error: empty assistant turn (stop_reason=end_turn, no text and no tool calls) - likely premature EOS
```

The wording is load-bearing:

- `"provider.?returned.?error"` matches pi-ai's
  `RETRYABLE_PROVIDER_ERROR_PATTERN`, so `isRetryableAssistantError()` returns
  true and agent-session auto-retries the assistant turn (default budget:
  `retry.maxRetries` = 3, `baseDelayMs` = 2000, exponential backoff).
- No `OVERFLOW_PATTERN` matches, so `isContextOverflow()` returns false and the
  error routes to **retry**, not compaction (compaction is disabled in this
  machine's pi settings — an overflow-classified error would fail hard).
- Errored assistant messages are excluded from the LLM context
  (pi-agent-core `context.js` `isContextMessage`), so the retry starts clean —
  the empty turn is never sent back to the model.

Thinking-only turns count as degenerate: a final assistant turn must carry
text or a tool call to be useful to the agent loop.

## Scope

- **Target:** `@earendil-works/pi-ai/dist/api/anthropic-messages.js`
  (nested under pi-coding-agent's `node_modules`; npm-root fallback probed).
  The legacy `dist/providers/anthropic.js` layout only re-exports
  `anthropicMessagesApi`, so this one file covers every layout.
- **Profiles:** all (no profile gate). The check is content-based and
  provider-agnostic: an empty `end_turn` turn is degenerate for any provider
  using the anthropic-messages API.
- **Anchor:** the single `if (output.stopReason === "pending") { … }` +
  `if (output.stopReason === "aborted" || …)` terminal-check block in
  `stream()`.

## Validation

`test.mjs` is the seam test: it drives the patched `stream()` against a mock
Anthropic SSE server using the exact degenerate shapes from session
transcripts, plus healthy shapes to prove no regression. Run it after every
pi upgrade that re-triggers the patch:

```sh
node ~/.local/share/pi-patches/empty-turn-retry/test.mjs
```

Expected: `empty-text` and `thinking-only` surface the retryable error;
`healthy-text` completes with `stopReason=stop` and `healthy-tooluse` with
`stopReason=toolUse`. Exit 0 on success.

## Failure modes

- **anchor-not-found (0 or >1 matches):** upstream changed the `stream()`
  terminal-check shape. Update the anchor in `patch.mjs` and bump
  `PATCH_REVISION`. If upstream started rejecting empty `end_turn` turns
  itself, delete this patch.
- **stale revision, no backup:** reinstall pi-coding-agent, then
  `chezmoi apply`.
- **Retry budget exhaustion:** if the model emits empty turns repeatedly, the
  3-retry budget bounds the loop and the error surfaces to the user. That is
  the intended fail-visible behavior.

## Related

- Gateway-side counterpart (not implemented): the same degenerate close could
  be caught in `apps/boost/litellm-image/anthropic_stream_fix.py`
  (`_axon_is_degenerate` currently only catches `max_tokens`) — that would fix
  Claude Code and Cursor clients on the same gateway too.
- Sibling patches: `anthropic-idle-watchdog` (same target file),
  `custom-message-marker` (patch structure template).
- Retry classification verified: `isRetryableAssistantError()` = true,
  `isContextOverflow()` = false for the patch's error message.
