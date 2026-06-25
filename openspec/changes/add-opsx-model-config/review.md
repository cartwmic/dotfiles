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

<!-- Model-config fields (author_model/review_models/impl_model/author_in_session
+ provider keys) are intentionally UNSET for this bootstrap change: the author-marker
gate check is what this change ADDS, so leaving `author` unconfigured means the gate
does not require an in-session marker on its own construction (source = unset). -->

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

**Diff Base SHA:** a7d19e5abcd9ec8787eab197adc3aeb8fe6e2e01
**Worktree Path:** /Users/cartwmic/.local/share/.opsx-worktrees/add-opsx-model-config
**Integration Branch:** main

## Manual Adjustments

- Model-config roles unset for this change (bootstrap: it defines the provenance gate).

## Execution Notes

- 2026-06-23 — Scale L. clarify 5 findings (0 blockers). Pre-impl adversarial review (opus + gpt-5.5) → 2 P0 + 12 findings applied: source-aware resolver, fail-closed enforcement, exact-match+alias, in-session marker, required review set. Rounds 2-4 converged (both APPROVE).
- 2026-06-23 — RE-SCOPE (user steer): provenance source moved to pi-subagents native run-history, bound by role agent identity, durable snapshot. Round-5 (opus) + round-6 (opus) review found a FUNDAMENTAL ceiling: a post-hoc gate cannot force a model against a same-UID actor (every gate-read source is worker-writable; the dispatch `agent` key is worker-chosen).
- 2026-06-23 — SCOPE DECISION (user): RIGHT-SIZE to resolver + author-in-session + cheap self-attested author marker; DROP run-history provenance enforcement (+ companion dependency, snapshot, agent-identity binding). ADD provider configuration (provider-qualified values + `provider` default/per-role keys). The observed bug is fixed at the source. Specs/design/tasks/clarify/plan rewritten. Round-8 convergence on the smaller surface PENDING.
