# Code Review

**Change:** refine-opsx-elision-token-budget
**Verdict:** pass
**review_mode:** adversarial-multimodel
**reviewer-provenance:** pi-subagents delegate — claude-bridge/claude-opus-4-8, openai-codex/gpt-5.5 (2 distinct models)
**Diff Base SHA:** 3b3fc2a768690b653ddad3875608d25a6d2ad5aa
**Reviewed Range:** 3b3fc2a768690b653ddad3875608d25a6d2ad5aa..0d1bf1ab4ce2ef3c4aee92657dc49a5d5ea9bb1f
**Attested HEAD:** 0d1bf1ab4ce2ef3c4aee92657dc49a5d5ea9bb1f
**Baseline:** intent.md + proposal + specs + plan + tasks status (no design.md — decision-gated, skipped at plain M)
**Generated:** 2026-07-08

## Round tracker

| Round | Mode | P0 | P1 | P2 | P3 | Reviewer verdicts | Reviewed HEAD |
|---|---|---|---|---|---|---|---|
| 1 | blind | 0 | 1 | 1 | 2 | opus:pass gpt:fail | 958d38c350ae6032ba3a66c09c9f4d27ab628724 |
| 2 | blind | 0 | 1 | 1 | 2 | opus:pass gpt:fail | dc42b52008e91b3d5db9c19fa09a9a2982917f43 |
| 3 | blind | 0 | 1 | 0 | 1 | opus:fail gpt:fail | 3b93eb7cfc3d383d989172498af6dacad66975f4 |
| 4 | blind | 0 | 1 | 0 | 0 | opus:pass gpt:fail | 31386a1023c124e088495cb91ea64776a7a7aba5 |
| 5 | disclosure-consensus | 0 | 0 | 0 | 1 | opus:pass gpt:pass | 31386a1023c124e088495cb91ea64776a7a7aba5 |
| 6 | blind (re-attest @ rebased HEAD) | 0 | 0 | 0 | 2 | opus:pass gpt:pass | 0d1bf1ab4ce2ef3c4aee92657dc49a5d5ea9bb1f |

<!-- Round 4's gpt dispatch first returned an infra crash (WebSocket closed, no
findings file) → INVALID, not counted; re-dispatched to a valid fail verdict.
Round 6: at archive time the branch was rebased onto main HEAD 8b869c0 to absorb
this change's own integration bookkeeping (locator/follow-ups/loop_hold) and make
the land-base current; the elision CODE is byte-identical across the rebase (empty
diff 31386a1..0d1bf1a for the extension files). The rebase moved the verdict-sealed
HEAD, so a fresh blind 2-model round re-attested at 0d1bf1a — both pass, only P3
advisories. Verdict re-sealed adversarial-multimodel at the rebased HEAD. -->

## Findings

| # | Finding | Severity | Status |
|---|---|---|---|
| 1 | R1 (gpt): `tokenBudgetBoundary` capped shed at the banded `allowedElide`, so an oldest turn exceeding it collapsed the boundary to 0 → fire-but-noop (over-budget view sent unchanged). | P1 | fixed |
| 2 | R2 (gpt): ceiling-walk boundary advanced every turn, dropping the frozen decision-3 band hysteresis (boundary not stable within a band). | P1 | fixed |
| 3 | R3 (opus+gpt): banded shed TARGET under-shed when a large stale turn sat after a small oldest turn → kept-full window exceeded `maxKeep+band` (retained the bloat the change targets). | P1 | fixed |
| 4 | R4 (gpt): kept-full window can dip below `maxKeep`, contradicting intent.md's `[maxKeep, maxKeep+band]` lower bound. | P1 | resolved (disclosure consensus: frozen intent is internally contradictory; not gating) |
| 5 | R2 (gpt, P3-per-opus): handler read real `usage.tokens` for a separate gate while the boundary used the estimate → a benign dual-total fire-but-noop path. | P3 | fixed (single-gated on the estimate) |
| 6 | intent.md Invariant/Decision 3 still state the impossible lower half `[maxKeep, maxKeep+band]`; reword to the achievable bound for future readers. | P3 | routed to follow-ups.md (frozen intent — advisory only) |

## Applied fixes

- `dc42b52` — reformulate the boundary to keep the most-recent turns fitting the ceiling (fixes finding 1).
- `3b93eb7` — band-quantize the shed target + single-gate the handler on the estimate (fixes findings 2, 5).
- `31386a1` — band-quantized shed FLOOR `ceil((total-ceiling)/band)*band` bounds the kept window ≤ ceiling for arbitrary turn sizes AND preserves band hysteresis (fixes finding 3); adds a non-tautological chunky-middle-turn test.

## Residual risks

- **Finding 4 (kept can dip below `maxKeep`).** The frozen intent is internally
  contradictory: decision 1 says "snap the boundary to a turn edge AT/BELOW the
  budget" (kept ≤ maxKeep) while decision 3 / Invariants say `[maxKeep, maxKeep+band]`
  (kept ≥ maxKeep). With indivisible turns (frozen non-goal: never split a turn),
  a turn straddling the boundary makes both bounds unsatisfiable simultaneously.
  The implementation honors decision 1 + the context-rot-relevant UPPER ceiling
  (`kept ≤ maxKeep+band` always) + the newest-turn carve-out, dipping below `maxKeep`
  only in the safe over-shed direction (shedding a large stale turn — the change's
  purpose). The disclosure-consensus round (both models) ruled this an ACCEPTABLE
  reconciliation, not a masked defect, requiring no human ruling. The delta-spec AC
  was restated to `≤ maxKeep+band, except a single newest turn` to encode this honestly.
- **Finding 6.** A future edit could tighten intent.md's Invariant wording to the
  achievable bound; deferred to follow-ups.md because intent.md is the frozen baseline
  (its MEANING is not edited by the loop).

## Verdict rationale

Six rounds (four blind + one disclosure-consensus + one blind re-attestation at the
rebased land-base HEAD). Rounds 1–3 surfaced genuine
correctness P1s (fire-but-noop, lost hysteresis, kept-window-over-ceiling), each fixed
with a landing commit and re-reviewed full-diff. Round 4's remaining P1 was not a code
defect but a dispute over an internally-contradictory frozen invariant; the single
sanctioned disclosure-consensus round (2 distinct models, opus + gpt) resolved it to
**pass** — the impossible-to-satisfy lower bound cannot gate the implementation, and the
code adopts the only reconciliation serving the change's bytes-bounded-window purpose.
Final round P0+P1 = 0. `bun test` → 92 pass / 0 fail. review_mode disclosure-consensus
with ≥2 distinct reviewer models satisfies the Constitution-IX multi-model requirement
for this existing-extension edit.
