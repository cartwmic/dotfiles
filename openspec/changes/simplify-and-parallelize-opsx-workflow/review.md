---
# Machine-readable mode block — the SOLE source opsx gate reads (it never parses
# the prose table below). Keep the table in sync as the human-facing mirror.
scale: XL
worktree_mode: worktree-required
execution_mode: standard
verification_mode: retained-required
debug_mode: standard
review_status: not-requested
delegation_mode: single-agent
code_review_mode: gating-required
loop_max_iterations: 80
validation_source_mode: required
spec_level: spec-anchored
doneness_mode: required
review_max_rounds: 5
review_models: [claude-bridge/claude-opus-4-8, openai-codex/gpt-5.5]
---

# Review

## Modes

| Mode | Value | Rationale |
|---|---|---|
| Scale | XL | Schema-surgery migration: gate CLI + extension + schema README/templates + spec consolidation (12→~8 capabilities) + skill surfaces; two coupled themes (audit-lean concurrency, workflow simplification) under one frozen intent |
| Worktree Mode | worktree-required | Code change (gate CLI, extension, schema, skills); isolation mandatory |
| Execution Mode | standard | Ordered migration steps carrying existing test suites; not TDD micro-tasks |
| Verification Mode | retained-required | Code change at Scale XL; AC↔test gate must be sealed |
| Debug Mode | standard | — |
| Review Status | not-requested | Set when gating review begins |
| Delegation Mode | single-agent | Single orchestrator; blind subagents for review/doneness verdicts only |
| Code Review Mode | gating-required | Constitution IX: edits existing skills (openspec-loop, openspec-propose, openspec-apply-change references, openspec-archive-change) → adversarial multi-model review mandatory |
| Loop Budget | 80 | XL-scale schema surgery; L/XL budget tier |
| Validation Source Mode | required | openspec/opsx-gates.yaml is the agent-independent manifest |
| Spec Level | spec-anchored | Deltas anchor to opsx-gate-enforcement, opsx-cli, opsx-workflow-schema, the consolidated loop + review capabilities, opsx-model-config, goal-loop |
| Doneness Mode | required | Scale XL ⇒ required; no waiver grounds |
| review_max_rounds | 5 | Convergence-discipline default, explicit |

## Diff Base + Worktree locator

**Diff Base SHA:** <set at worktree creation>
**Worktree Path:** <set at worktree creation>

## Execution Notes

- 2026-07-03: switchboard authored from frozen intent.md (fbc9ad9). Scale XL per
  intent §Scale; gated under the CURRENT 5-tier schema even though this change
  itself collapses tiers (forward-only migration, intent §Constraints).
- Note: this change's own A2 rule (path-scoped main commits) is practiced from
  this commit onward: all integration-checkout commits for this change use
  `git commit -- openspec/changes/simplify-and-parallelize-opsx-workflow` scoping.
