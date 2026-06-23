---
scale: M
worktree_mode: worktree-required
execution_mode: standard
verification_mode: retained-recommended
debug_mode: standard
review_status: not-requested
delegation_mode: single-agent
code_review_mode: gating-required
loop_max_iterations: 40
validation_source_mode: required
spec_level: spec-anchored
---

# Review

## Modes

| Mode | Value | Notes |
|---|---|---|
| Scale | M | new pi extension, single capability |
| Execution Mode | standard | — |
| Verification Mode | retained-recommended | verify.md produced, not hard-gated |
| Debug Mode | standard | — |
| Review Status | not-requested | post-impl code-review gates (M default) |
| Delegation Mode | single-agent | — |
| Worktree Mode | worktree-required | default; runs in opsx/<change> worktree |
| Code Review Mode | gating-required | M default; code-review.md must pass before archive |
| Loop Max Iterations | 40 | Scale-M budget |
| Validation Source Mode | required | repo opsx-gates.yaml satisfies it |
| Spec Level | spec-anchored | — |

## Diff Base + Worktree locator

**Diff Base SHA:** e637ef5c0b30509ca9fcba61317f6f3e26ef859e
**Worktree Path:** /Users/cartwmic/.local/share/.opsx-worktrees/add-opsx-loop-kickoff
**Integration Branch:** main

## Manual Adjustments

- Code Review Mode = gating-required (M default kept) — exercises the post-impl gate this harness exists for.

## Execution Notes

- 2026-06-23 — Scale M, spec-anchored. clarify 5 findings, 0 blockers.
