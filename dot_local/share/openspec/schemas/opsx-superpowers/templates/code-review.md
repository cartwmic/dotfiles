# Code Review

<!--
Post-implementation adversarial review of the ACTUAL diff, distinct from the
pre-implementation analyze review. Skill-managed (NOT in the schema artifact
graph) — produced by openspec-apply-change after the pre-review checks are green,
authored by the review SUBAGENT (never self-authored by the orchestrator).

opsx gate / archive read these fields verbatim:
  - Verdict             pass | fail            (gating-required: fail/absent blocks archive)
  - review_mode         adversarial-multimodel | disclosure-consensus | degraded-single-model
                        (degraded does NOT satisfy gating or Constitution IX;
                         disclosure-consensus = the single sanctioned NON-blind
                         consensus round — satisfies multi-model gating only when
                         it consolidates ≥2 distinct reviewer models)
  - reviewer-provenance adapter-stamped reviewer identity (absence = failed check)
  - Diff Base SHA       the immutable base the review was computed against
  - Reviewed Range      <Diff Base SHA>..<implementation HEAD>  (must equal current → freshness)
  - waived_by_user      OPTIONAL; present only when the user waived remaining open
                        P0/P1 findings at the decision-audit landing. Lists waived
                        finding #s + rationale; authorizes a re-sealed pass with the
                        reviewed range unchanged. NEVER self-authored by the loop.
-->

**Change:** <change-name>
**Verdict:** <pass | fail>
**review_mode:** <adversarial-multimodel | disclosure-consensus | degraded-single-model>
**reviewer-provenance:** <subagent id(s) stamped by the subagent-dispatch adapter>
**Diff Base SHA:** <immutable base from review.md>
**Reviewed Range:** <Diff Base SHA>..<implementation HEAD>
**Baseline:** intent.md + proposal + specs + design + plan + tasks status
**Generated:** YYYY-MM-DD
<!-- **waived_by_user:** <finding #s + user rationale> — only after an explicit user
     waiver at the decision-audit landing; reviewed range stays unchanged -->

## Verdict contract (embed in every reviewer dispatch prompt)

<!-- Baseline-bounded contract (opsx-adversarial-review): a reviewer may FAIL
     this review ONLY for (a) a violation of the frozen baseline — intent.md,
     delta ACs, design decisions, constitution/domain — or (b) an
     objective correctness/security defect, even where the baseline is silent. Taste,
     style, alternative-design preference, and beyond-scope demands are
     advisory (P2/P3) and cannot gate.

     Severity rubric — single lens, cite the violated baseline element:
       P0  confirmed baseline violation or critical correctness/security defect
       P1  must-fix gap within the contract (violates baseline or objectively wrong)
       P2  should-fix advisory (real improvement, not contract-violating)
       P3  nit
     Verdict: pass ⇔ no open P0/P1. Open P2/P3 are recorded as warnings and
     never force a further fix round. -->

## Round tracker

<!-- Orchestrator-sealed round ledger (opsx-adversarial-review). One row per
     gating round, INCLUDING any disclosure round. Consolidated counts = MAX
     across reviewers per severity that round (no cross-reviewer finding
     matching). Reviewer verdicts column: e.g. "opus:fail gpt:pass".
     NEVER include this ledger, prior-round findings, or another reviewer's
     output in a BLIND reviewer prompt — only the single marked disclosure
     round may disclose.

     Continuation/stop conditions (quiet-round default — after each round,
     land the fixes FIRST, then evaluate IN ORDER):
       a quiet round — latest round P0+P1 = 0 → seal pass, stop
       b converging  — findings open AND change-scoped fixes landed since the
                       round AND rounds < review_max_rounds → next round
                       autonomously, NO human ruling
       c thrash      — findings open AND no fix landed → disclosure/landing
       d hard cap    — rounds ≥ review_max_rounds (default 5) →
                       disclosure/landing regardless of trajectory
     WHERE review.md sets review_budget_mode: land-on-stop (opt-in, and the
     reading of any unknown value): stop instead on flat-or-rising P0+P1
     across the two most recent rounds, or on budget exhaustion.
     Stops with open P0/P1 route to the disclosure round (persistent split)
     and then the decision-audit landing — never a forced green, never
     additional ad-hoc reviewer models; quiet-round automates CONTINUE only,
     never SEAL. A user resume ruling at the landing grants a recorded budget
     extension (note it in this table). -->

| Round | Mode | P0 | P1 | P2 | P3 | Reviewer verdicts | Reviewed HEAD |
|---|---|---|---|---|---|---|---|
| 1 | blind | 0 | 0 | 0 | 0 | <model:verdict …> | <sha> |

## Findings

<!-- Neutral heading by design: consolidated counts use the max-across-reviewers
     rule — there is NO cross-reviewer finding matching ("convergence") step. -->

<!-- MANDATORY check: if the diff Diff Base SHA..HEAD touches
     openspec/opsx-gates.yaml (or any gate/validation manifest), flag it
     explicitly and verify the change WEAKENS nothing (removed gates,
     required->false flips) without recorded human authorization — the gate
     reads its manifest from the integration checkout, so a manifest edit is
     the one remaining self-weakening vector diff review must catch. -->

| # | Finding | Severity | Status |
|---|---|---|---|
| 1 | <description> | P0\|P1\|P2\|P3 | open\|fixed\|deferred |

## Applied fixes

- <commit / change addressing each P0/P1>

## Residual risks

- <anything accepted without a fix + rationale>

## Verdict rationale

<!-- One paragraph: why pass or fail. pass requires P0+P1 = 0 against the baseline
and, for Constitution-IX (skill-editing) changes, a multi-model review_mode:
adversarial-multimodel, or disclosure-consensus when it consolidated ≥2 distinct
reviewer models. degraded-single-model never satisfies Constitution IX. -->
