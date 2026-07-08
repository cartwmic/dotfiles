## 1. Pure elision helpers (helpers.ts)

- [ ] 1.1 Add `resolveElideThresholdTokens(contextWindow, pctRaw, tokRaw)` mirroring
      `resolveCompactThresholdTokens`, plus `OPSX_ELIDE_AT_PERCENT` (default 25) /
      `OPSX_ELIDE_AT_TOKENS` (default 60000) resolution; `off/none/false/0` on a term
      drops it, both off disables, garbage → default.
      (AC opsx-loop-context-elision.threshold-band-gating)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/helpers.ts
  - allow_new_files: false
- [ ] 1.2 Add `elideBoundary(total, keepRecent, band)` computing the band-quantized
      boundary index (recent-K full, boundary snapped to `OPSX_ELIDE_BAND_TURNS`
      default 5) so the slim prefix is stable within a band.
      (AC opsx-loop-context-elision.threshold-band-gating)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/helpers.ts
  - allow_new_files: false
- [ ] 1.3 Add `elideToolResultBodies(messages, opts)` returning a NEW view: replace
      text bodies of tool-result messages before the boundary with the stub, keep the
      messages/pairing, keep tool calls + assistant/user text + thinking + recent-K
      results; fail-closed (return original) if a structural/pairing check fails;
      never mutate the input array/messages.
      (ACs opsx-loop-context-elision.stale-tool-result-body-elision,
       opsx-loop-context-elision.structural-integrity-fail-closed,
       opsx-loop-context-elision.no-history-mutation,
       opsx-loop-context-elision.deterministic-no-model-call)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/helpers.ts
  - allow_new_files: false

## 2. Extension wiring (index.ts)

- [ ] 2.1 Add `elided?: boolean` to `LoopState` (per-run flag, reset when a new
      worker turn/run starts).
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/index.ts
  - allow_new_files: false
- [ ] 2.2 Register the pi `context` event handler behind `typeof` guards: no-op
      unless `loop?.active`; measure usage via `getContextUsage()`; below threshold
      or missing APIs → return messages unchanged; at/above → call
      `elideToolResultBodies` and set `loop.elided = true` when a body was elided.
      (ACs opsx-loop-context-elision.active-loop-scoped-elision,
       opsx-loop-context-elision.safe-degradation)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/index.ts
  - allow_new_files: false
- [ ] 2.3 Wire the elision→compaction coupling: in `agent_end`, when `loop.elided`
      is set, treat the run as over the L1 compaction threshold (force the compact
      path in `continueWorker`); clear `loop.elided` at run start.
      (AC opsx-loop-context-elision.elision-to-compaction-coupling)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/index.ts
  - allow_new_files: false

## 3. Tests (helpers.test.ts)

- [ ] 3.1 Unit tests for `resolveElideThresholdTokens` / `elideBoundary` (defaults,
      off-terms, garbage, band quantization, at/below-L1 invariant across window
      sizes) and `elideToolResultBodies` (old body → stub, recent-K preserved,
      pairing preserved, non-tool content preserved, fail-closed on malformed input,
      input not mutated). Cite ACs by canonical ID in test strings.
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/helpers.test.ts
  - allow_new_files: false
