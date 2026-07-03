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
doneness_mode: required
---

# Review

## Modes

| Mode | Value | Notes |
|---|---|---|
| Scale | L | Cross-capability (loop-orchestration + post-impl-review + workflow-schema templates), edits existing skills (Constitution IX), ADR-worthy decisions (verdict contract, disclosure round, trajectory stop) |
| Execution Mode | standard | Spec/skill/template prose edits; no strict TDD |
| Verification Mode | retained-required | verify.md green is an archive HARD-GATE |
| Debug Mode | standard | — |
| Review Status | resolved | 2 blind rounds + 1 disclosure-consensus round converged (pass, 0 open P0/P1) |
| Delegation Mode | single-agent | Authored in-session; reviews delegated to blind subagents |
| Worktree Mode | worktree-required | ADR-0008 |
| Code Review Mode | gating-required | Constitution IX (existing-skill edits) → multi-model adversarial |
| Loop Max Iterations | 80 | Scale L |
| Validation Source Mode | required | opsx-gates.yaml / repo validators |
| Spec Level | spec-anchored | default |
| Doneness Mode | required | Default at Scale ≥ M; judge machinery already shipped (add-opsx-doneness-judge) |

## Diff Base + Worktree locator

**Diff Base SHA:** d45ce8446662429ae276d8ca86d2781cd45f4143
**Worktree Path:** /Users/cartwmic/.local/share/.opsx-worktrees/add-opsx-review-convergence
**Integration Branch:** main

## Manual Adjustments

- None; all defaults for Scale L retained (worktree-required, gating-required code review, retained-required verify, doneness required).

## Execution Notes

- 2026-07-03 — review.md authored; Scale L per frozen intent (cross-capability, Constitution IX).
- 2026-07-03 — review role model unset (`opsx models` all unset); blind reviews dispatched on session model `claude-bridge/claude-opus-4-8`; recorded as the resolved review set for model-stability purposes.
- 2026-07-03 — analyze returned BLOCKED (1 blocker, 4 major, 3 minor); all resolved in-session: F1 budget extension on resume ruling; F2 waiver-sealed pass (`waived_by_user`); F3 consolidated round count = max across reviewers; F4 landing halts loop continuation; F5 proposal skill path corrected to canonical `dot_local/share/agent-harness/canonical/skills/openspec-loop/SKILL.md`; F6 MODIFIED Adversarial Review With Degradation (disclosure round = sole sanctioned non-blind exception); F7 analyze ledger surface = appended `Round Ledger` section of analyze.md; F8 loop-orchestration widening binding thinned to reference the discipline.

## Scope Expansions

<!-- Evidence-gated widenings per intent.md decision "Prose scope + evidence-gated
widening". One bullet per widening: what widened + the evidence it is required to
meet the frozen intent. Empty until/unless the loop widens scope. -->

- 2026-07-03 — added `tests/opsx-review-convergence/test_review_convergence_surfaces.sh`
  (deterministic grep assertions that the discipline text exists in templates/skills)
  plus a required `opsx-gates.yaml` entry — evidence: verify.md check 5 (forward
  AC↔test mapping) requires ≥1 TEST file citing each canonical AC ID, and the frozen
  intent's enforcement-layer decision (skill prose + structured fields) produced a
  prose-only diff with zero test files; verify green is unreachable without it
  (Verification Mode retained-required). Strengthens the gate (adds a required
  validator; weakens nothing).
