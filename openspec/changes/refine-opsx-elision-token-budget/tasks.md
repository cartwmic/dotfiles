## 1. Token-budget helpers (helpers.ts)

- [ ] 1.1 Remove the retired turn-count resolvers and boundary helper:
      `resolveElideThresholdTokens`, `resolveElidePercent`, `resolveElideTokens`,
      `resolveElideKeepRecent`, `resolveElideBand`, `elideBoundary`, and the
      `OPSX_ELIDE_AT_PERCENT` / `OPSX_ELIDE_AT_TOKENS` / `OPSX_ELIDE_KEEP_RECENT_TURNS`
      / `OPSX_ELIDE_BAND_TURNS` reads.
      (AC opsx-loop-context-elision.token-budget-boundary)
  - intent: refactor
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/helpers.ts
  - allow_new_files: false
- [ ] 1.2 Add `resolveElideKeepPercent(raw)` (default 40, min 1, max 100) and
      `resolveElideBandPercent(raw)` (default 5, min 1) reading
      `OPSX_ELIDE_KEEP_RECENT_PERCENT` / `OPSX_ELIDE_BAND_PERCENT`; garbage → default,
      `off/none/false/0`-style handled consistently with the existing compact
      resolvers.
      (AC opsx-loop-context-elision.token-budget-boundary,
       opsx-loop-context-elision.token-band-hysteresis)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/helpers.ts
  - allow_new_files: false
- [ ] 1.3 Add `resolveElideMaxKeepTokens(contextWindow, pctRaw)` = `pct% × window`
      (no absolute floor) and `resolveElideBandTokens(contextWindow, pctRaw)` =
      `pct% × window`, plus a deterministic per-turn token estimator
      (content chars ÷ 4, no tokenizer/model call).
      (AC opsx-loop-context-elision.token-budget-boundary,
       opsx-loop-context-elision.token-band-hysteresis)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/helpers.ts
  - allow_new_files: false
- [ ] 1.4 Add `tokenBudgetBoundary(messages, maxKeepTokens, bandTokens)` returning the
      turn-snapped boundary index: walk turns newest→oldest accumulating estimated
      tokens, snap the boundary to the last turn edge keeping the recent window within
      `[maxKeep, maxKeep + band]`, quantize advance by `bandTokens` for cache
      stability, and ALWAYS keep the newest turn even if it alone exceeds the budget.
      (ACs opsx-loop-context-elision.token-budget-boundary,
       opsx-loop-context-elision.token-band-hysteresis)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/helpers.ts
  - allow_new_files: false
- [ ] 1.5 Adapt `elideToolResultBodies(messages, opts)` to consume the
      `tokenBudgetBoundary` result instead of `elideBoundary(total, keepRecent, band)`;
      preserve the existing fail-closed structural/pairing guards, stub text, idempotence,
      and non-mutation of the input array.
      (ACs opsx-loop-context-elision.stale-tool-result-body-elision,
       opsx-loop-context-elision.token-budget-boundary)
  - intent: refactor
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/helpers.ts
  - allow_new_files: false

## 2. Extension wiring (index.ts)

- [ ] 2.1 Rewire the `context` handler: resolve `maxKeep`/`band` from
      `getContextUsage().contextWindow` via the new percent resolvers; gate on
      `total > maxKeep + band` (retiring `resolveElideThresholdTokens`); call
      `elideToolResultBodies` with the token-budget boundary; keep the active-loop-only
      and `typeof` degrade guards; set `loop.elided = true` when a body was elided.
      (ACs opsx-loop-context-elision.active-loop-scoped-elision,
       opsx-loop-context-elision.token-budget-boundary,
       opsx-loop-context-elision.safe-degradation)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/index.ts
  - allow_new_files: false
- [ ] 2.2 Add the compaction-suppression guard: `if (session.compacting) return
      undefined;` at the top of the `context` handler so the compaction summarizer's own
      request is never elided.
      (AC opsx-loop-context-elision.elision-suppressed-during-compaction)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/index.ts
  - allow_new_files: false
- [ ] 2.3 Consume/clear `session.elided` on the distill (`awaitingChange`) continuation
      path too, so the elision→compaction coupling is honored at every run boundary
      (matching the existing worker `agent_end` path).
      (AC opsx-loop-context-elision.elision-to-compaction-coupling)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/index.ts
  - allow_new_files: false

## 3. Tests (helpers.test.ts)

- [ ] 3.1 Replace the turn-count helper tests with token-budget tests:
      `resolveElideKeepPercent` / `resolveElideBandPercent` (defaults, garbage,
      off-terms, bounds); `resolveElideMaxKeepTokens` / `resolveElideBandTokens`
      (percent-of-window, no floor, across window sizes); `tokenBudgetBoundary` (window
      bounded to `[maxKeep, maxKeep+band]`, boundary snaps to turn edge, band
      quantization stable within a band + advances across a band, newest turn always
      kept even when it alone exceeds budget); and `elideToolResultBodies` over the token
      boundary (old body → stub, recent window preserved, pairing preserved, non-tool
      content preserved, fail-closed on malformed input, input not mutated). Cite ACs by
      canonical ID in test strings.
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/helpers.test.ts
  - allow_new_files: false
