---
scale: M
full_rigor: false
execution_mode: standard
verification_mode: retained-recommended
debug_mode: standard
review_status: not-requested
delegation_mode: subagent-required
loop_max_iterations: 40
validation_source_mode: required
spec_level: spec-anchored
doneness_mode: required
---

# Review

## Modes

| Mode | Value | Notes |
|---|---|---|
| Scale | M | typical feature — full graph; clarify folds into proposal, analyze deterministic-only, doneness rides code-review dispatch |
| full_rigor | false | plain M — no standalone clarify/analyze/design, no independent doneness judge |
| Execution Mode | standard | standard test-after implementation |
| Verification Mode | retained-recommended | unit tests retained for the pure elision helpers |
| Debug Mode | standard | |
| Review Status | not-requested | |
| Delegation Mode | subagent-required | 2-model blind code review dispatched via pi-subagents |
| Code Review Mode | derived (absent) | M ⇒ gating-required — blocks archive on code-review.md Verdict |
| Loop Max Iterations | 40 | M budget |
| Validation Source Mode | required | `bun test` on the opsx-loop extension is the agent-independent source |
| Doneness Mode | required | doneness rides the code-review dispatch's designated reviewer (first `review` model) |
| Spec Level | spec-anchored | |
| Model Config | (unset) | resolves via user `~/.config/opsx/models.yaml` (review = opus-4-8 + gpt-5.5) |

## Diff Base + Worktree locator

**Diff Base SHA:** <empty until apply captures it>
**Worktree Path:** <empty until apply captures it>
**Integration Branch:** <detected-at-capture>

## Manual Adjustments

- Delegation Mode set to `subagent-required`: this is a Constitution-IX-adjacent
  extension change; the 2-model blind adversarial code review is gating-required at
  Scale M and must dispatch via the subagent-dispatch hook.

## Execution Notes

- 2026-07-07 — change proposed in-session (author-in-session); clarify open
  questions resolved inline in proposal.md, analyze run deterministic-only.

## Scope Expansions

<!-- none yet -->

## Fidelity Round Ledger

<!-- design.md is decision-gated and NOT authored at plain M (D3/D5), so no
design-fidelity dispatch applies to this change. -->
