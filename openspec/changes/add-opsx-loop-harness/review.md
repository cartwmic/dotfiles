---
scale: L
worktree_mode: worktree-required
execution_mode: standard
verification_mode: retained-required
debug_mode: standard
review_status: resolved
delegation_mode: subagent-eligible
code_review_mode: gating-required
loop_max_iterations: 80
validation_source_mode: required
spec_level: spec-anchored
---

# Review

<!--
Controlled-vocabulary mode switchboard. The apply instruction and opsx-gate read
these. opsx-gate reads the machine-readable front-matter above (decision D5b);
the table below is the human-facing mirror.
-->

## Modes

| Mode | Value | Notes |
|---|---|---|
| Scale | L | Cross-capability + edits existing skills + constitution touch; adversarial review invoked at analyze |
| Execution Mode | standard | Not a debugging/TDD-driven change |
| Verification Mode | retained-required | verify.md must be green before archive |
| Debug Mode | standard | — |
| Review Status | resolved | Round-1 blind adversarial review complete; findings applied (analyze.md appendices) |
| Delegation Mode | subagent-eligible | Reviews + validation judgments delegated to subagents |
| Worktree Mode | worktree-required | Default for all Scales; this change runs in an isolated worktree |
| Code Review Mode | gating-required | Post-impl code-review.md must pass before archive |
| Loop Max Iterations | 80 | Scale-L default budget |
| Spec Level | spec-anchored | OpenSpec-natural mode |

## Diff Base + Worktree locator

<!-- Captured by apply at worktree creation. Diff Base SHA = integration-branch
merge-base, immutable for the life of the branch. opsx-gate reads these to locate
the worktree and recompute the verdict-freshness range. -->

**Diff Base SHA:** a02d70c46f4d177a12c9a5a1ddbb6ae6ae3b0593
**Worktree Path:** /Users/cartwmic/.local/share/.opsx-worktrees/add-opsx-loop-harness
**Integration Branch:** main

## Manual Adjustments

- Worktree Mode = worktree-required at Scale L (and as the new all-Scales default this change introduces) — the autonomous loop needs blast-radius containment.
- Verification Mode = retained-required (stricter than the retained-recommended default) because this change edits enforcement-critical skills.
- Code Review Mode = gating-required — this change is the one that defines post-impl review; it must dogfood its own gate.

## Execution Notes

- 2026-06-20 — Scale L + spec-anchored selected up front.
- 2026-06-20 — clarify produced 7 findings; 3 blockers resolved by owner (A1 ready-to-archive, I1 absent-review-fails-gate, C2 preserve-worktree).
- 2026-06-20 — adversarial review round 1 (gpt-5.5 + deepseek-v4-pro, blind) → REQUEST-CHANGES; 2 P0 + 7 P1 convergent findings applied to specs/design; opus-direct reviewer failed on provider usage cap.
- 2026-06-20 — adversarial review round 2 (claude-opus-4-8 via claude-bridge, blind) → REQUEST-CHANGES; 1 P0 (verdict freshness/provenance) + 5 P1 applied; design D9/D10 added.
- 2026-06-20 — round 3 final-validation (opus + gpt-5.5, blind) → REQUEST-CHANGES; 0 P0, convergent P1 coherence breaks from prior patches (front-matter sole-source, degraded-review-fails-IX, command-judge MODIFIED, intent.md required, immutable Diff Base SHA) applied.
- 2026-06-20 — round 4 re-validation (opus + gpt-5.5, blind) → REQUEST-CHANGES; 0 P0, 3 P1 (dual base-SHA field, same-tree base, missing intent.md, baseline omission, validation cwd) applied; intent.md authored for this change.
- 2026-06-20 — round 5: opus APPROVE; gpt 1 P1 (Delegation Mode pi coupling) → rewritten as harness-neutral subagent-dispatch hook.
- 2026-06-20 — round 6 final sign-off: BOTH opus + gpt-5.5 APPROVE, 0 P0/P1. Adversarial-review-cycle CONVERGED (stop condition: both approve). Review Status = resolved.
