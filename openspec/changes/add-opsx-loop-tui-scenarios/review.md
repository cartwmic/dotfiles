---
scale: M
full_rigor: false
execution_mode: standard
verification_mode: retained-recommended
debug_mode: standard
review_status: not-requested
delegation_mode: single-agent
loop_max_iterations: 40
validation_source_mode: required
spec_level: spec-anchored
doneness_mode: required
---

# Review

## Modes

| Mode | Value | Notes |
|---|---|---|
| Scale | M | Cross-file test-suite capability for `opsx-loop`; matches frozen intent suggested Scale M |
| full_rigor | false | Deterministic TUI suite and normal review discipline are enough; no ADR/top-tier extras intended |
| Execution Mode | standard | Test-suite implementation, no TDD-required override |
| Verification Mode | retained-recommended | Retain verification evidence without requiring separate verify gate unless later needed |
| Debug Mode | standard | No systematic-debugging mode unless a failing scenario requires it |
| Review Status | not-requested | No review dispatched yet |
| Delegation Mode | single-agent | Authoring in-session; blind reviews still delegated when gate reaches judgment steps |
| Code Review Mode | derived (absent) | Scale M derives gating-required code review |
| Loop Max Iterations | 40 | Scale M default |
| Validation Source Mode | required | Scenario suite must provide agent-independent validation commands |
| Doneness Mode | required | Scale M requires sealed doneness judgment |
| Spec Level | spec-anchored | Specs drive scenario coverage |
| Model Config | (unset) | Use configured/default opsx role models |

## Diff Base + Worktree locator

**Diff Base SHA:** 728884b4ed6cf2e83dafba9f01cd000f816e962c
**Worktree Path:** /Users/cartwmic/.local/share/chezmoi--opsx-add-opsx-loop-tui-scenarios
**Integration Branch:** main

## Manual Adjustments

- Scale M selected from frozen intent: cross-file TUI scenario suite within one capability, no planned runtime semantic change.

## Execution Notes

- 2026-07-06 14:08 — Seeded review switchboard from frozen intent; assume deterministic fake provider plus fake `opsx` default suite, optional real-model smoke skipped by default.
- 2026-07-06 14:12 — Published worktree locator from `opsx worktree ensure add-opsx-loop-tui-scenarios`.

## Scope Expansions

- None.

## Fidelity Round Ledger

| Round | Fidelity | Per-judge verdicts | Attested HEAD |
|---|---|---|---|
