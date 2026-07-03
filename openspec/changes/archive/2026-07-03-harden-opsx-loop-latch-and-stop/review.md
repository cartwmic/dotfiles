---
# Machine-readable mode block — the SOLE source opsx gate reads (it never parses
# the prose table below). Keep the table in sync as the human-facing mirror.
scale: M
worktree_mode: worktree-required
execution_mode: standard
verification_mode: retained-required
debug_mode: standard
review_status: resolved
delegation_mode: single-agent
code_review_mode: gating-required
loop_max_iterations: 40
validation_source_mode: required
spec_level: spec-anchored
doneness_mode: required
review_max_rounds: 5
loop_hold: true
loop_hold_reason: "gate green at 863192d; terminal landing — awaiting human archive ruling"
review_models: [claude-bridge/claude-opus-4-8, openai-codex/gpt-5.5]
---

# Review

## Modes

| Mode | Value | Rationale |
|---|---|---|
| Scale | M | Extension TypeScript + gate CLI + opsx-loop-kickoff spec deltas + two skill-prose surfaces; one behavioral theme (loop stops and locates correctly) |
| Worktree Mode | worktree-required | Code change (extension + gate); isolation mandatory |
| Execution Mode | standard | Ordered steps; TS edits carry existing test suite, not TDD micro-tasks |
| Verification Mode | retained-required | Code change at Scale M; AC↔test gate must be sealed |
| Debug Mode | standard | — |
| Review Status | resolved | Disclosure-consensus pass sealed (3 rounds, 2 models) |
| Delegation Mode | single-agent | Single orchestrator; blind subagents for review/doneness verdicts only |
| Code Review Mode | gating-required | Constitution IX: edits existing skills (openspec-loop, openspec-apply-change reference) → adversarial multi-model review mandatory |
| Loop Budget | 40 | M-scale code change; headroom over the S default without L's 80 |
| Validation Source Mode | required | openspec/opsx-gates.yaml is the agent-independent manifest |
| Spec Level | spec-anchored | Deltas anchor to opsx-loop-kickoff + related capabilities |
| Doneness Mode | required | Scale M ⇒ required; no waiver grounds |
| review_max_rounds | 5 | Convergence-discipline default, explicit |

## Diff Base + Worktree locator

**Diff Base SHA:** d84a2e4f9ed0aeef52529ab14c00db8fe4e7c15a
**Worktree Path:** /Users/cartwmic/.local/share/.opsx-worktrees/harden-opsx-loop-latch-and-stop
**Integration Branch:** main

## Manual Adjustments

- code_review_mode: gating-required (template default advisory) — Constitution IX, this change edits existing skill prose surfaces.
- verification_mode: retained-required (template default retained-recommended) — extension/gate code change; AC↔test traceability must be sealed, not sampled.
- loop_max_iterations: 40 (template default 20) — M-scale code diff across 4 gap workstreams.
- review_models pinned to the resolved review set (model-stability rule: blind rounds locked to this set for the whole change).

## Execution Notes

- 2026-07-03 — review.md authored; Scale M per frozen intent (4 gaps G-A..G-D, one behavioral theme). Baseline: intent.md at 22ca87b.
- Known in-scope finding logged pre-apply: distill stall guard off-by-one — turn-1 evaluation initializes lastDirs (prevDirs === undefined ⇒ dirsChanged) so STALL_LIMIT=3 costs 4 distill turns and the stall notify's "after 3 turns" undercounts; fix by seeding lastDirs from preChangeDirs at arm (captured at index.ts:404) or by correcting the notify wording. Observed live this session during the pre-arm distill turns.

## Scope Expansions

<!-- Evidence-gated widenings beyond the frozen intent prose, logged per the
opsx-review-convergence discipline. None yet. -->
