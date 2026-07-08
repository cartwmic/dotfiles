<!-- authored: in-session -->

## Why

The shipped context-elision boundary (`add-opsx-loop-context-elision`, archived
2026-07-08, decision 2) keeps "the most recent K turns" — a *turn* count guarding
an *unbounded* byte payload. Measured on session
`019f3d32-76d6-7469-b42d-d05cd51c8d28` (38-turn run, gpt-5.5 272k window),
`keepRecent=3` kept only ~2.4k tokens when the recent turns were small assistant
nudges, but would keep ~40k if those turns were large `read`/`grep` dumps — a ~17×
swing on the same knob. The recent-K window was meant to bound the model's working
set; a turn count does not. A token budget does.

## What Changes

- **BREAKING (internal env surface).** Replace the turn-count elision boundary with
  a **token-budget boundary** snapped to turn edges: keep the most-recent turns
  whose cumulative estimated tokens fit `maxKeep`, elide stale tool-result bodies
  before that turn-snapped boundary. Supersedes `add-opsx-loop-context-elision`
  decision 2.
- `maxKeep` defaults to **40% of the live context window**
  (`OPSX_ELIDE_KEEP_RECENT_PERCENT`, default 40) — dynamic per model, no absolute
  token floor. Holds the working context below the context-rot-heavy zone on any
  window size.
- **Token-band hysteresis** for prompt-cache stability: advance the boundary only
  every `OPSX_ELIDE_BAND_PERCENT` (default 5% of window) of growth. Kept-full window
  is bounded to `[maxKeep, maxKeep + band]`.
- **Retire the separate activation threshold.** `maxKeep` subsumes the shipped
  `OPSX_ELIDE_AT_PERCENT` (25) / `OPSX_ELIDE_AT_TOKENS` (60000) gate: elision fires
  when `total > maxKeep + band`. **BREAKING:** the env knobs
  `OPSX_ELIDE_KEEP_RECENT_TURNS`, `OPSX_ELIDE_BAND_TURNS`, `OPSX_ELIDE_AT_PERCENT`,
  `OPSX_ELIDE_AT_TOKENS` and the helpers `resolveElideThresholdTokens`,
  `resolveElidePercent`, `resolveElideTokens`, `resolveElideKeepRecent`,
  `resolveElideBand`, `elideBoundary` are removed.
- Per-turn tokens estimated from content character length (÷4) — no tokenizer or
  model call in the transform; estimation error only shifts the boundary by at most
  one turn.
- **Fold in two predecessor round-5 advisories** (same `context` handler): guard the
  handler with `if (session.compacting) return undefined;` (never elide the
  compaction summarizer's own request), and consume/clear `session.elided` on the
  distill (`awaitingChange`) continuation path so the coupling is honored at every
  run boundary.
- **Non-breaking to end users / behavior.** Defaults keep the same active-loop-only,
  fail-closed, no-history-mutation, elision→compaction-coupling behavior; pi general
  auto-compaction stays off. Only the internal env-knob surface changes.

## Capabilities

### New Capabilities

<!-- none — refines the existing runtime capability. -->

### Modified Capabilities

- `opsx-loop-context-elision`: the elision boundary becomes a token budget
  (`maxKeep = 40% of window`) snapped to turn edges with token-band hysteresis,
  replacing the turn-count `recent-K` window and the separate percent/token
  activation threshold; the compaction coupling is consumed on the distill path too,
  and elision is suppressed during compaction.

## Impact

- **Affected files:**
  - `dot_pi/agent/extensions/opsx-loop/helpers.ts` — remove the turn-count resolvers
    (`resolveElideThresholdTokens`, `resolveElidePercent`, `resolveElideTokens`,
    `resolveElideKeepRecent`, `resolveElideBand`, `elideBoundary`); add token-budget
    resolvers (`resolveElideKeepPercent`, `resolveElideBandPercent`,
    `resolveElideMaxKeepTokens`, `resolveElideBandTokens`), a per-turn token
    estimator, and a `tokenBudgetBoundary(...)` that snaps to a turn edge under the
    banded budget; adapt `elideToolResultBodies` to consume the token-snapped
    boundary.
  - `dot_pi/agent/extensions/opsx-loop/index.ts` — rewire the `context` handler to
    resolve `maxKeep`/`band` from `getContextUsage().contextWindow`, gate on
    `total > maxKeep + band`, add the `session.compacting` guard, and consume
    `session.elided` on the distill continuation path.
  - `dot_pi/agent/extensions/opsx-loop/helpers.test.ts` — replace turn-count tests
    with token-budget-boundary tests.
- **APIs / dependencies:** unchanged — still the pi `context` / `transformContext`
  hook and `getContextUsage()` behind `typeof` guards; no new npm dependencies.
- **Composition:** unchanged — layers above L1 (between-turns compaction) and L2
  (overflow recovery); does NOT re-enable pi built-in auto-compaction
  (`compaction.enabled` stays `false`).

## Deterministic analyze (plain-M, inline)

- **Tiling / traceability:** every "What Changes" bullet maps to a modified/added
  `opsx-loop-context-elision` requirement (token-budget boundary, token-band
  hysteresis, retired-threshold gating, stale-body elision over the token window,
  distill-path coupling, elision-suppressed-during-compaction, determinism). No
  orphan requirement; no uncovered bullet. Carried-over requirements (structural
  integrity, no-history-mutation, safe-degradation, active-loop scope) are unchanged
  in the spec-of-record.
- **EARS lint:** error/unwanted ACs use `IF…THEN` (host-API absence, structural
  guard); nominal ACs use `WHILE`/`WHEN`. No `should`/`may` in normative lines; each
  normative SHALL statement is a single line.
- **Blockers:** none.

## Open Questions

Clarify-in-proposal (plain-M): each resolved in place under a 2-option discipline.

1. **`maxKeep` default.** Decision: **40% of the live context window**, dynamic, no
   absolute floor (frozen intent decision 2). *(A) 40%-of-window (chosen — scales
   across models, holds working set below context-rot zone); (B) fixed absolute cap
   à la the shipped 60k floor (rejected — does not scale across window sizes).*
2. **Band size default.** Decision: **5% of window** (`OPSX_ELIDE_BAND_PERCENT=5`;
   ≈13.6k on gpt-5.5 272k). *(A) 5%-of-window (chosen — bounds cache misses to
   boundary-advance events while keeping the kept-full window within
   `[maxKeep, maxKeep+band]`); (B) a smaller fixed token band (rejected — reintroduces
   the absolute-cap-does-not-scale problem the token budget exists to fix).*
3. **Retire vs keep the separate activation threshold.** Decision: **retire** —
   `maxKeep` subsumes it; elision fires when `total > maxKeep + band` (frozen intent
   decision 4). *(A) retire the `OPSX_ELIDE_AT_*` gate (chosen — one budget governs
   both activation and boundary, fewer knobs to reason about); (B) keep a distinct
   lower activation gate (rejected — two coupled knobs for no behavioral benefit
   given maxKeep already gates).*
4. **Newest turn when it alone exceeds the budget.** Decision: **always keep the
   newest (in-flight) turn in full**, even if it alone exceeds `maxKeep` (carried
   invariant). *(A) always keep newest turn (chosen — the model is mid-reasoning on
   it; eliding it breaks the in-flight request); (B) elide toward budget even into
   the newest turn (rejected — violates the frozen "newest turn always full"
   invariant and risks pairing breakage).*
