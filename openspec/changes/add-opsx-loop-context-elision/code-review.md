# Code Review

**Change:** add-opsx-loop-context-elision
**Verdict:** pass
**review_mode:** adversarial-multimodel
**reviewer-provenance:** pi-subagents `delegate` × 2 — claude-bridge/claude-opus-4-8, openai-codex/gpt-5.5
**Diff Base SHA:** b0dd6bf96af3899767c613a9f317295dc3446722
**Reviewed Range:** b0dd6bf96af3899767c613a9f317295dc3446722..4bbdf21e220ef2c460fb46be905237089baa8500
**Attested HEAD:** 4bbdf21e220ef2c460fb46be905237089baa8500
**Baseline:** intent.md + proposal + specs + plan + tasks status
**Generated:** 2026-07-08

## Round tracker

| Round | Mode | P0 | P1 | P2 | P3 | Reviewer verdicts | Reviewed HEAD |
|---|---|---|---|---|---|---|---|
| 1 | blind | 0 | 1 | 0 | 3 | opus:pass gpt:fail | 564f3b3146d758ce1969ae414d9bd890be465fe2 |
| 2 | blind | 0 | 1 | 0 | 3 | opus:pass gpt:fail | cd7cbb449f3854bacbcfaef1b7b81aa2fc679911 |
| 3 | blind | 0 | 0 | 1 | 2 | opus:pass gpt:pass | d9b5624f441bd322b98dbb08ca0eba719906f9aa |
| 4 | blind (re-attest post-rebase) | 0 | 1 | 0 | 1 | opus:pass gpt:fail | b43cd923df00f57749930c1b0e5a88ea384624a9 |
| 5 | blind | 0 | 0 | 1 | 1 | opus:pass gpt:pass | 4bbdf21e220ef2c460fb46be905237089baa8500 |

Consolidated counts = max across reviewers per severity (no cross-reviewer matching).
Rounds 1–3 ran on the original base; the branch was then cleanly rebased onto
current main (`ac92b54`, an unrelated TUI-test commit + this change's own
integration bookkeeping — no elision-code change), staleness-firing a fresh
re-attestation. Round 4 surfaced a residual P1 (elision latch leaked across the
L2 overflow-retry boundary), fixed in `4bbdf21`; round 5 is quiet (0 P0/P1 across
both distinct models) → sealed pass.

## Findings

| # | Finding | Severity | Status |
|---|---|---|---|
| 1 | R1: structural fail-closed guard unreachable — orphan/malformed old tool_result could be stubbed and returned. | P1 | fixed |
| 2 | R2: old tool_result with valid id but non-array content passed the pairing check while siblings were elided. | P1 | fixed |
| 3 | R4: `session.elided` not cleared on the L2 overflow compact-and-retry boundary → a later non-elided retry run could take an elision-driven compaction (violates the "non-elided run unaffected" scenario). | P1 | fixed |
| 4 | R5: `context` handler has no `!session.compacting` guard — IF pi ever emitted the context event during `ctx.compact()` it could re-set `elided`/feed stubs to the summarizer. Unverifiable here; round-3 analysis found compaction bypasses `transformContext`, so likely moot. | P2 | deferred |
| 5 | R5: distill-mode (`awaitingChange`) runs set `elided` but never reach `continueWorker`; the abort/error branch clears it, so no false-compaction — a benign coupling miss, not a fail-safe violation. | P3 | deferred |
| 6 | R3: whole-pass fail-closed when any tool_result has non-array content (theoretical — pi's `ToolResultMessage.content` is always an array). | P2 | deferred |
| 7 | R3/R5: elision replaces entire tool_result `content` with the text stub, dropping non-text (image) blocks — within intent; safe direction. | P3 | deferred |

## Applied fixes

- R1 → `cd7cbb4`/`00cb759`: collect assistant tool-call ids; fail closed on an orphan tool_result.
- R2 → `d9b5624`/`ccb6718`: fail closed when a tool_result `content` is not a block array.
- R4 → `4bbdf21`: clear `session.elided` at the error/abort run boundary (overflow branch compacts there anyway).

(SHAs `00cb759`/`ccb6718` are the post-rebase equivalents of `cd7cbb4`/`d9b5624`.)

## Residual risks

- Findings 4–7 are advisory (P2/P3), non-gating. #4 (`compacting` guard) and #5
  (distill coupling) are recommended follow-ups and land naturally in the
  token-budget successor change, which edits the same `context` handler. #6/#7
  were routed to `follow-ups.md` at the first landing. None violate the frozen
  baseline or a delta AC.

## Verdict rationale

Two distinct blind reviewer models reviewed the full diff against the frozen
baseline across five rounds (three pre-rebase, two post-rebase re-attestation);
both attested HEAD `4bbdf21…` and the worktree root at seal. Each P1 was fixed and
re-reviewed on a fresh blind full-diff round; round 5 is quiet (0 P0/P1 across both
models). Pairing preservation, no-history-mutation, fail-closed structural guards,
threshold-at/below-L1, band-stable boundary, active-loop-only no-op, once-per-run
coupling at every agent_end exit, and no re-enable of pi auto-compaction all
verified. `review_mode: adversarial-multimodel` satisfies the gating-required code
review and Constitution-IX. Pass.
