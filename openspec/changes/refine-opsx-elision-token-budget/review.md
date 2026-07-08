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
| Verification Mode | retained-recommended | unit tests retained for the pure token-budget helpers |
| Debug Mode | standard | |
| Review Status | not-requested | |
| Delegation Mode | subagent-required | 2-model blind adversarial code review dispatched via pi-subagents (Constitution-IX: existing-extension edit) |
| Code Review Mode | derived (absent) | M ⇒ gating-required — blocks archive on code-review.md Verdict |
| Loop Max Iterations | 40 | M budget |
| Validation Source Mode | required | `bun test` on the opsx-loop extension is the agent-independent source |
| Doneness Mode | required | doneness rides the code-review dispatch's designated reviewer (first `review` model) |
| Spec Level | spec-anchored | |
| Model Config | (unset) | resolves via user `~/.config/opsx/models.yaml` (review = claude-bridge/claude-opus-4-8 + openai-codex/gpt-5.5; impl = openai-codex/gpt-5.5) |

## Diff Base + Worktree locator

<!-- Populated at apply time by `opsx worktree ensure refine-opsx-elision-token-budget`. -->

**Diff Base SHA:** (pending worktree ensure)
**Worktree Path:** (pending worktree ensure)
**Integration Branch:** main

## Manual Adjustments

- Delegation Mode set to `subagent-required`: Constitution-IX existing-extension
  edit; the 2-model blind adversarial code review is gating-required at Scale M and
  must dispatch via the subagent-dispatch hook. A `degraded-single-model` verdict
  does not satisfy the gate.
- design.md deliberately NOT authored (plain-M decision-gated): all trade-offs are
  frozen upstream in `intent.md` (token-budget boundary, 40%-of-window maxKeep,
  5%-of-window band, retire-the-threshold, char/4 estimate); no NEW decision is made
  at propose time, so no ADR candidate and no design-fidelity dispatch applies.

## Execution Notes

- 2026-07-08 — change proposed in-session (author-in-session); clarify open
  questions resolved inline in proposal.md, analyze run deterministic-only. Successor
  to archived `add-opsx-loop-context-elision`; supersedes its decision 2 (turn-count
  boundary). Branches from a main that already contains the shipped turn-count
  elision.

## Scope Expansions

<!-- none yet -->

## Fidelity Round Ledger

<!-- design.md is decision-gated and NOT authored at plain M (D3/D5), so no
design-fidelity dispatch applies to this change. -->
