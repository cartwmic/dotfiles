<!--
Doneness verdict — the SEALED intent-satisfaction judgment opsx gate reads.

Skill-managed (NOT in the schema artifact graph) — produced by the openspec-loop
orchestration AFTER the mechanical gate checks pass, authored by an independent BLIND
doneness SUBAGENT on the resolved `review` role model (never self-authored by the
orchestrator). The gate reads these fields verbatim; it runs NO language model.

opsx gate reads (required WHILE Scale >= M and review.md `doneness_mode: required`):
  - Doneness            satisfied | not      (gating: not/absent => failed check)
  - Judge               adapter-stamped reviewer-provenance (the review-role model /
                        dispatch adapter identity). Its review_mode must NOT be
                        degraded-single-model, else the verdict is a failed check.
  - Frozen-Intent SHA   sha256 of the change's intent.md the judge read; the gate
                        recomputes and compares (mutated intent => failed check).
  - Diff Base SHA       must equal review.md's immutable Diff Base SHA.
  - Reviewed Range      <Diff Base SHA>..<implementation HEAD>; must equal the range
                        the gate recomputes from the located worktree HEAD (a new
                        commit invalidates a prior verdict => re-judge).

When Doneness is `not`, enumerate every unmet intent gap as a bullet under `## Gaps`
using a short STABLE phrase per bullet (the stall detector normalizes and compares the
gap SET across turns; a persistently identical gap set halts a thrashing loop). Rule
`satisfied` ONLY when the frozen intent's stated outcomes are met — NEVER demand
beyond-scope / gold-plated work.
-->

# Doneness

**Doneness:** not

**Judge:** <review-role model id / dispatch-adapter provenance>
**review_mode:** blind-single-judge
<!-- review_mode vocabulary: blind-single-judge (the normal case — ONE
     independent blind subagent judge) | adversarial-multimodel (optional
     stronger form, >= 2 distinct models). degraded-single-model (inline,
     no dispatch adapter) and unknown values FAIL the gate. -->
**Frozen-Intent SHA:** <sha256 of intent.md>
**Diff Base SHA:** <immutable Diff Base SHA from review.md>
**Reviewed Range:** <Diff Base SHA>..<implementation HEAD>

## Verdict rationale

<!-- 1-3 sentences: how the diff does / does not meet the frozen intent's outcomes. -->

## Gaps

<!-- Present ONLY when Doneness: not. One short stable phrase per unmet intent outcome.
Omit this section entirely when Doneness: satisfied. -->
- <unmet intent outcome, as a short stable phrase>
