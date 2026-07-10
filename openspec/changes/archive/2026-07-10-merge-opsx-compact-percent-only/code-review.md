# Code Review

**Change:** merge-opsx-compact-percent-only
**Verdict:** pass
**review_mode:** adversarial-multimodel
**reviewer-provenance:** pi-subagents dispatch — openai-codex/gpt-5.6-sol, claude-bridge/claude-fable-5 (blind, parallel, cwd pinned to the opsx/merge-opsx-compact-percent-only worktree; findings files /tmp/opsx-cr-merge-compact/r{1,2,3}-*.md)
**Diff Base SHA:** 2d0bcd1355f5b5e7bd37939013dd88f0f4437b71
**Reviewed Range:** 2d0bcd1355f5b5e7bd37939013dd88f0f4437b71..7c53341192acdcef422d8649ae2fc2edb5eeee1f
**Attested HEAD:** 7c53341192acdcef422d8649ae2fc2edb5eeee1f
**Baseline:** intent.md + proposal + specs (opsx-loop-compaction-guard delta) + plan + tasks status (no design.md — plain Scale M)
**Generated:** 2026-07-10

## Round tracker

| Round | Mode | P0 | P1 | P2 | P3 | Reviewer verdicts | Reviewed HEAD |
|---|---|---|---|---|---|---|---|
| 1 | blind | 0 | 1 | 1 | 2 | gpt-5.6-sol:fail fable-5:pass | e7c829151abae972b0a5ab1321e8f3236ea0f5d9 |
| 2 | blind | 0 | 0 | 0 | 3 | gpt-5.6-sol:pass fable-5:pass | 179ddae7dace3d89dffb5ad5377f7568f73d419c |
| 3 | blind | 0 | 0 | 1 | 3 | gpt-5.6-sol:pass fable-5:pass | 7c53341192acdcef422d8649ae2fc2edb5eeee1f |

Rounds 1–2 attested pre-rebase commit SHAs (e7c8291 / 179ddae). At archive time the
branch was rebased onto integration HEAD ba6eabc per the archive-check base-currency
remedy (content-identical rebase, disjoint files: 3053f9a→6f2eb4c, e7c8291→ffcd8c2,
179ddae→7c53341); the rebase staleness-fired round 3, a fresh blind full-diff
re-review at the rebased HEAD — quiet round (P0+P1 = 0, max across reviewers) →
sealed pass. Round 3's P2/P3 counts re-observe the same advisories already routed to
follow-ups.md (no new findings). All rounds' read-only dual-tree windows verified
clean; every counted verdict carried a valid attestation matching its dispatched
range head and the worktree root.

## Findings

| # | Finding | Severity | Status |
|---|---|---|---|
| 1 | R1 (gpt-5.6-sol): replacement surface-test assertions under-constrained — fragments `` `gating-required` at Scale M`` + `omitting the key` did not pin the DEFAULT derivation or omission-cannot-skip semantics | P1 | fixed (7c53341, pre-rebase 179ddae — 4 doctrine-pinning assertions) |
| 2 | R1/R3 (fable-5): surface-test repair is outside the intent's declared ripple / task file contracts | P2 | recorded — pre-declared in review.md Scope Expansions with evidence (pre-existing red on main from 3928abb); advisory, follow-ups.md #1 |
| 3 | R1–R3 (fable-5): `index.ts` Lever A comment implied opt-in behavior; residual awkward line break after fix | P3 | fixed in substance; formatting nit open, follow-ups.md #3 |
| 4 | R1–R3 (fable-5): arity-reflection test (`resolveCompactThresholdTokens.length === 2`) is a brittle proxy for the retired env term | P3 | open (warning), follow-ups.md #2 |
| 5 | R2/R3 (fable-5): surface assertion 1 literal `DEFAULTS to` is loose on its own | P3 | open (warning), follow-ups.md #4 |

## Applied fixes

- 7c53341192acdcef422d8649ae2fc2edb5eeee1f (pre-rebase 179ddae) —
  fix(opsx-review-convergence): pin skill assertions to full default-derivation
  doctrine (4 assertions replacing 2); refresh Lever A comment in index.ts to
  default-on percent-only phrasing. Addresses finding 1 (P1) and finding 3 substance.

## Residual risks

- Open P3 warnings (findings 3 formatting, 4, 5) accepted: advisory nits, no
  baseline element violated; routed to follow-ups.md.
- Environments still exporting `OPSX_COMPACT_AT_TOKENS` will have it silently
  ignored — intended per the frozen intent's constraints (no code path reads it).

## Verdict rationale

Round 3 blind full-diff re-review (staleness-fired by the archive-time rebase) by
both configured review models returned pass with zero open P0/P1 (max across
reviewers) — the second consecutive quiet round on content-identical trees. The
percent-only implementation covers every delta AC of `opsx-loop-compaction-guard`
(default 50, ceil semantics, explicit-off-only disable, garbage→default
never-silent-disable, unknown-window degradation, 50-over-40 elision layering,
single-term policy line); `bun test` 94/94 and the convergence surface suite 170/0
are green; no gate manifest is touched; the one validation-surface edit strengthens
enforcement (1 stale assertion → 4 doctrine-pinning assertions,
mutation-checked in R2 and re-verified in R3). Multi-model adversarial mode
satisfied with 2 distinct reviewer models attesting the same HEAD.
