---
scale: L
worktree_mode: worktree-required
execution_mode: standard
verification_mode: retained-recommended
debug_mode: standard
review_status: resolved
delegation_mode: single-agent
code_review_mode: gating-required
loop_max_iterations: 80
validation_source_mode: required
spec_level: spec-anchored
---

# Review

<!-- Model-config fields (author_model/review_models/impl_model/author_in_session)
are intentionally UNSET for this bootstrap change: the model-provenance gate check
is what this change ADDS, so leaving roles unconfigured means the gate does not
enforce provenance on its own construction (source = unset). -->

## Modes

| Mode | Value | Notes |
|---|---|---|
| Scale | L | new capability + edits existing skills + gate; adversarial review at analyze |
| Verification Mode | retained-recommended | verify.md produced, not hard-gated |
| Code Review Mode | gating-required | post-impl adversarial code-review must pass (Constitution IX) |
| Worktree Mode | worktree-required | runs in opsx/<change> worktree |
| Loop Max Iterations | 80 | Scale-L budget |
| Validation Source Mode | required | repo opsx-gates.yaml satisfies it |
| Review Status | resolved | round-1 pre-impl adversarial review applied (analyze appendix) |

## Diff Base + Worktree locator

**Diff Base SHA:** <empty until apply captures it>
**Worktree Path:** <empty until apply captures it>
**Integration Branch:** main

## Manual Adjustments

- Model-config roles unset for this change (bootstrap: it defines the provenance gate).

## Execution Notes

- 2026-06-23 — Scale L. clarify 5 findings (0 blockers). Pre-impl adversarial review (opus + gpt-5.5) → 2 P0 + 12 findings applied: source-aware resolver, fail-closed enforcement, exact-match+alias, in-session marker, required review set.
