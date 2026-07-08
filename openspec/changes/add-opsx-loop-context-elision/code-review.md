# Code Review

**Change:** add-opsx-loop-context-elision
**Verdict:** pass
**review_mode:** adversarial-multimodel
**reviewer-provenance:** pi-subagents `delegate` × 2 — claude-bridge/claude-opus-4-8, openai-codex/gpt-5.5
**Diff Base SHA:** b0dd6bf96af3899767c613a9f317295dc3446722
**Reviewed Range:** b0dd6bf96af3899767c613a9f317295dc3446722..d9b5624f441bd322b98dbb08ca0eba719906f9aa
**Attested HEAD:** d9b5624f441bd322b98dbb08ca0eba719906f9aa
**Baseline:** intent.md + proposal + specs + plan + tasks status
**Generated:** 2026-07-08

## Round tracker

| Round | Mode | P0 | P1 | P2 | P3 | Reviewer verdicts | Reviewed HEAD |
|---|---|---|---|---|---|---|---|
| 1 | blind | 0 | 1 | 0 | 3 | opus:pass gpt:fail | 564f3b3146d758ce1969ae414d9bd890be465fe2 |
| 2 | blind | 0 | 1 | 0 | 3 | opus:pass gpt:fail | cd7cbb449f3854bacbcfaef1b7b81aa2fc679911 |
| 3 | blind | 0 | 0 | 1 | 2 | opus:pass gpt:pass | d9b5624f441bd322b98dbb08ca0eba719906f9aa |

Consolidated counts are the max across reviewers per severity (no cross-reviewer
matching). Round 3 is a quiet round (P0+P1 = 0 across both distinct models) →
sealed pass. Each round's P1 was fixed and re-reviewed on a fresh full-diff blind
round (converging; no human ruling, no disclosure round consumed).

## Findings

| # | Finding | Severity | Status |
|---|---|---|---|
| 1 | R1: structural fail-closed guard was unreachable (only a length check); an orphan/malformed old tool_result could be stubbed and returned as an elided view (spec Structural Integrity Fail Closed / intent "MUST NOT orphan a tool_result"). | P1 | fixed |
| 2 | R2: an old tool_result with a valid toolCallId but non-array `content` passed the pairing check while valid siblings were still elided, emitting a partially-transformed view rather than failing closed. | P1 | fixed |
| 3 | R3: whole-pass fail-closed when ANY tool_result (incl. recent) has non-array content — if pi ever emitted string-content results, elision would go permanently inert (degrade-safe no-op; pi's ToolResultMessage.content is always an array, so theoretical). | P2 | deferred |
| 4 | R3: `session.elided` is consumed only on the worker-mode `continueWorker` path, not literally "at run start"; abnormal/distill agent_end paths can defer the coupled compaction by one turn (never double-compacts, never misses). | P3 | deferred |
| 5 | R3: elision replaces the entire tool_result `content` with a single text stub, dropping any non-text (image) blocks rather than only the text body — within intent (whole stale output is the bloat); safe direction. | P3 | deferred |

## Applied fixes

- R1 → commit `cd7cbb4`: collect assistant tool-call ids; fail closed (return
  original, `elided:false`) when any tool_result references no matching tool_call.
- R2 → commit `d9b5624`: extend the structural pre-scan to fail closed when any
  tool_result `content` is not a well-formed block array.

## Residual risks

- Findings 3–5 are advisory (P2/P3), routed to `follow-ups.md`. None violate the
  frozen baseline or a delta AC; each is either degrade-safe or within the intent's
  stated scope. The P2 (broad fail-closed) is theoretical given pi's typed
  `ToolResultMessage.content: (TextContent|ImageContent)[]` (always an array).

## Verdict rationale

Two distinct blind reviewer models (claude-bridge/claude-opus-4-8,
openai-codex/gpt-5.5) reviewed the full diff `b0dd6bf..d9b5624` against the frozen
baseline over three rounds; both attested HEAD `d9b5624…` and the worktree root.
Each round's P1 was fixed and re-reviewed on a fresh blind full-diff round; round 3
is quiet (0 P0/P1 across both models). Pairing preservation, no-history-mutation,
fail-closed structural guards, threshold-at/below-L1, band-stable boundary,
active-loop-only no-op, once-per-run coupling, and no re-enable of pi
auto-compaction all verified. `review_mode: adversarial-multimodel` (≥2 distinct
models) satisfies the gating-required code review and Constitution-IX. Pass.
