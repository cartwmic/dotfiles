<!-- authored: in-session -->
---
scale: L
worktree_mode: worktree-required
execution_mode: standard
verification_mode: retained-required
debug_mode: standard
review_status: resolved
delegation_mode: single-agent
code_review_mode: gating-required
loop_max_iterations: 80
validation_source_mode: required
spec_level: spec-anchored
doneness_mode: waived
doneness_waiver_rationale: >
  Bootstrap. This change INTRODUCES the doneness judge and the gate's doneness
  check. Requiring this change to self-gate on a doneness verdict produced by the
  very machinery under construction (in this same worktree's opsx binary) is
  circular. Doneness is waived for this bootstrapping change only; it becomes
  required (default) for every subsequent Scale >= M change once this ships.
---

# Review

## Modes

| Mode | Value | Notes |
|---|---|---|
| Scale | L | Cross-capability + breaking; ADR-worthy |
| Execution Mode | standard | Bash/TS + spec/skill edits; not strict TDD |
| Verification Mode | retained-required | verify.md green is an archive HARD-GATE |
| Debug Mode | standard | — |
| Review Status | resolved | 4 blind adversarial rounds converged (both APPROVE, 0 P0/0 P1) |
| Delegation Mode | single-agent | Authored/implemented in-session; review delegated to blind subagents |
| Worktree Mode | worktree-required | ADR-0008 |
| Code Review Mode | gating-required | Constitution IX (skill edits) → multi-model adversarial |
| Loop Max Iterations | 80 | Scale L |
| Validation Source Mode | required | opsx-gates.yaml / test suites |
| Spec Level | spec-anchored | default |
| Doneness Mode | waived | **bootstrap** — see front-matter rationale |

## Diff Base SHA

- **Diff Base SHA:** 30d6d7917b5b342c7ab89d1138ccecae41a9c58d
- **Worktree Path:** /Users/cartwmic/.local/share/.opsx-worktrees/add-opsx-doneness-judge
- **Integration Branch:** main

## Manual Adjustments

- `doneness_mode: waived` for this change only (bootstrap circularity). Every
  subsequent Scale ≥ M change defaults to `doneness_mode: required`.

## Execution Notes

- _(appended during apply)_
