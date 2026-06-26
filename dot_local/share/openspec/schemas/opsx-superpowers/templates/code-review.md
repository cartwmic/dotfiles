# Code Review

<!--
Post-implementation adversarial review of the ACTUAL diff, distinct from the
pre-implementation analyze review. Skill-managed (NOT in the schema artifact
graph) — produced by openspec-apply-change after the pre-review checks are green,
authored by the review SUBAGENT (never self-authored by the orchestrator).

opsx gate / archive read these fields verbatim:
  - Verdict             pass | fail            (gating-required: fail/absent blocks archive)
  - review_mode         adversarial-multimodel | degraded-single-model
                        (degraded does NOT satisfy gating or Constitution IX)
  - reviewer-provenance adapter-stamped reviewer identity (absence = failed check)
  - Diff Base SHA       the immutable base the review was computed against
  - Reviewed Range      <Diff Base SHA>..<implementation HEAD>  (must equal current → freshness)
-->

**Change:** <change-name>
**Verdict:** <pass | fail>
**review_mode:** <adversarial-multimodel | degraded-single-model>
**reviewer-provenance:** <subagent id(s) stamped by the subagent-dispatch adapter>
**Diff Base SHA:** <immutable base from review.md>
**Reviewed Range:** <Diff Base SHA>..<implementation HEAD>
**Baseline:** intent.md + proposal + specs + design + plan + tasks status
**Generated:** YYYY-MM-DD

## Round tracker

| Round | P0 | P1 | P2 | P3 | Approvals |
|---|---|---|---|---|---|
| 1 | 0 | 0 | 0 | 0 | 0/N |

## Convergent findings

| # | Finding | Severity | Status |
|---|---|---|---|
| 1 | <description> | P0\|P1\|P2\|P3 | open\|fixed\|deferred |

## Applied fixes

- <commit / change addressing each P0/P1>

## Residual risks

- <anything accepted without a fix + rationale>

## Verdict rationale

<!-- One paragraph: why pass or fail. pass requires P0+P1 = 0 against the baseline
and an adversarial-multimodel review_mode for Constitution-IX (skill-editing) changes. -->
