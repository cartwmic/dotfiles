# Intent — refine-opsx-elision-token-budget

Status: explore-frozen

## Intent

Supersede the turn-count elision boundary shipped in
add-opsx-loop-context-elision (archived 2026-07-08; decision 2, "older than the
most recent K turns") with a TOKEN-BUDGET boundary snapped to turn edges. The
turn-count keeps a recent working set whose BYTE size swings with turn size:
measured on session `019f3d32-76d6-7469-b42d-d05cd51c8d28` (38-turn run,
gpt-5.5 272k window), `keepRecent=3` kept only ~2.4k tokens when the recent
turns were small assistant nudges, but would keep ~40k if those turns were big
`read`/`grep` dumps — a ~17× swing on the same knob. A token budget keeps a
predictable, bytes-bounded recent window regardless of turn sizes, which is the
property the "recent-K window" was meant to provide.

## Frozen design decisions

1. **Token-budget boundary.** Keep the most-recent turns whose cumulative
   ESTIMATED tokens fit a budget `maxKeep`; elide stale tool-result bodies before
   that boundary. Snap the boundary to a TURN edge at/below the budget (never split
   a turn — `tool_call ↔ tool_result` pairing stays intact). Replaces the
   turn-count boundary and `elideBoundary(total, keepRecent, band)`.

2. **maxKeep = 40% of the context window** (dynamic; NO absolute token floor).
   `OPSX_ELIDE_KEEP_RECENT_PERCENT` (default 40) resolves against the live
   `getContextUsage().contextWindow`. Holds the model's working context near 40%
   of window — below the context-rot-heavy zone — on any window size. Rejected: an
   absolute token cap (the shipped 60k-style floor), which does not scale across
   models.

3. **Token-band hysteresis for cache stability.** Advance the boundary only every
   `OPSX_ELIDE_BAND_PERCENT` (default 5% of window) of new growth, so the slim
   prefix stays stable across requests and re-caches after a boundary advance.
   Kept-full window is bounded to `[maxKeep, maxKeep + band]`. Replaces the
   turn-count band (`OPSX_ELIDE_BAND_TURNS`).

4. **Retire the separate activation threshold.** maxKeep (40%) subsumes the
   shipped `OPSX_ELIDE_AT_PERCENT` (25) / `OPSX_ELIDE_AT_TOKENS` (60000) gate and
   `resolveElideThresholdTokens`: elision fires when `total > maxKeep + band`. Those
   knobs and `OPSX_ELIDE_KEEP_RECENT_TURNS` are REMOVED. The L1 between-turns
   compaction threshold and its `OPSX_COMPACT_AT_*` knobs are UNCHANGED.

5. **Deterministic token estimate.** Per-turn tokens are estimated from content
   character length (÷4) — NO tokenizer or model call in the transform. Estimation
   error only shifts the boundary by at most one turn; it never breaks pairing or
   correctness.

## Folded-in advisories (from the predecessor's round-5 review)

This change edits the same `context` handler, so it also lands two advisory
follow-ups recorded in the predecessor's code-review.md:
- Add a `if (session.compacting) return undefined;` guard to the `context` handler
  (defensive: never elide the compaction summarizer's own request).
- Consume/clear `session.elided` on the distill (`awaitingChange`) continuation
  path too, so the coupling is honored uniformly at every run boundary.

## Carried over unchanged (from add-opsx-loop-context-elision)

- Active-loop-only scope; ephemeral per-request view; no stored-history mutation.
- Fail-closed structural/pairing validation (orphan and non-array tool-result
  content); system prompt and the newest (in-flight) turn always sent in full.
- Elision→compaction coupling (`LoopState.elided`) consumed once per run at
  `agent_end` (all exit paths).
- Degrade-safe `typeof` guards; pi general auto-compaction stays off
  (`compaction.enabled` untouched).
- Thinking blocks still untouched (the ~20k-token residual floor is the
  compaction coupling's job; thinking-elision remains deferred).

## Constraints

- No LLM/tokenizer call in the per-request transform (deterministic char/4 estimate).
- MUST NOT orphan a tool_result from its tool_call; MUST preserve the newest turn
  and the system prompt; fail closed to a no-op on any structural anomaly.
- Degrade safely when `getContextUsage`/`context` hook are absent (no-op).
- Compose with L1 (between-turns compaction) and L2 (overflow recovery); do NOT
  re-enable pi built-in auto-compaction.

## Invariants

- The kept-full recent window is bounded to `[maxKeep, maxKeep + band]` tokens.
- Elision never mutates stored session history — per-request view only.
- `tool_call ↔ tool_result` pairing preserved in every emitted view.

## Non-goals

- Eliding thinking blocks (still deferred).
- Global / interactive-session trimming (a future standalone extension).
- Changing the L1 between-turns compaction thresholds or the L2 overflow path.
- Splitting a turn to hit the budget exactly (boundary snaps to turn edges only).

## Supersedes

- add-opsx-loop-context-elision decision 2 (turn-count boundary) and its
  `OPSX_ELIDE_KEEP_RECENT_TURNS` / `OPSX_ELIDE_BAND_TURNS` /
  `OPSX_ELIDE_AT_PERCENT` / `OPSX_ELIDE_AT_TOKENS` knobs, plus the helpers
  `resolveElideThresholdTokens`, `resolveElidePercent`, `resolveElideTokens`,
  `resolveElideKeepRecent`, `resolveElideBand`, and `elideBoundary`.
