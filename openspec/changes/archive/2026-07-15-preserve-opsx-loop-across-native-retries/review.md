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
review_models: [openai-codex/gpt-5.6-sol, claude-bridge/claude-opus-4-8]
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
| Model Config | review override | `openai-codex/gpt-5.6-sol` + `claude-bridge/claude-opus-4-8` after configured Fable reviewer exhausted provider quota before producing any valid judgment |

## Diff Base + Worktree locator

**Diff Base SHA:** a5cc8de5040107e121a199caf845358a395b98d0
**Worktree Path:** /Users/cartwmic/.local/share/chezmoi--opsx-preserve-opsx-loop-across-native-retries
**Integration Branch:** main

## Manual Adjustments

- Scale set to M rather than S because the correction spans runtime lifecycle handling, capability specification, focused tests, and likely TUI scenario coverage while remaining one capability.
- Review model set repaired before the first gating code-review round: configured `claude-bridge/claude-fable-5` returned only a provider quota-limit message and no valid attestation/verdict; substituted available same-provider `claude-bridge/claude-opus-4-8` alongside configured `openai-codex/gpt-5.6-sol` so blind multi-model gating remains reachable.

## Execution Notes

- 2026-07-14 — Frozen intent selects hybrid lifecycle handling: clean `agent_end` retains existing continuation topology; only unresolved errors defer to `agent_settled`.
- 2026-07-14 — Validation dispatch incident: `claude-bridge/claude-fable-5` exhausted provider quota before reading the tree; output lacked attestation/verdict and was excluded as INVALID. Blind retry used `openai-codex/gpt-5.6-sol`, which returned red findings; lifecycle gaps and commit-body hygiene were fixed before gating review.

## Scope Expansions

<!-- none -->

## Fidelity Round Ledger

<!-- No rounds yet. Author design.md only if proposal/spec work confirms a decision requiring it. -->
