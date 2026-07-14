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

<!-- authored: in-session -->

## Modes

| Mode | Value | Notes |
|---|---|---|
| Scale | M | Cross-file lifecycle correction within the existing `opsx-loop` capability |
| full_rigor | false | No migration, breaking change, cross-capability architecture, or new retry policy |
| Execution Mode | standard | Regression-first coverage is expected, but strict red/green ordering is not required |
| Verification Mode | retained-recommended | Retain focused lifecycle tests and run the extension test suite |
| Debug Mode | standard | Root cause and Pi lifecycle ordering were established during explore |
| Review Status | not-requested | No separate pre-implementation adversarial review requested |
| Delegation Mode | single-agent | Implementation is tightly coupled within one extension; gating review still uses blind subagents |
| Code Review Mode | derived (absent) | Scale M derives `gating-required` |
| Loop Max Iterations | 40 | Scale M authoring default |
| Validation Source Mode | required | Extension test suite and deterministic fake lifecycle events provide agent-independent validation |
| Doneness Mode | required | Plain-M doneness rides the designated blind code reviewer dispatch |
| Spec Level | spec-anchored | Existing `opsx-loop` capability spec is updated with the lifecycle contract |
| Model Config | (unset) | Resolve project/user role models through `opsx models` |

## Diff Base + Worktree locator

**Diff Base SHA:** <empty until apply captures it>
**Worktree Path:** <empty until apply captures it>
**Integration Branch:** <detected-at-capture>

## Manual Adjustments

- Scale set to M rather than S because the correction spans runtime lifecycle handling, capability specification, focused tests, and likely TUI scenario coverage while remaining one capability.

## Execution Notes

- 2026-07-14 — Frozen intent selects hybrid lifecycle handling: clean `agent_end` retains existing continuation topology; only unresolved errors defer to `agent_settled`.

## Scope Expansions

<!-- none -->

## Fidelity Round Ledger

<!-- No rounds yet. Author design.md only if proposal/spec work confirms a decision requiring it. -->
