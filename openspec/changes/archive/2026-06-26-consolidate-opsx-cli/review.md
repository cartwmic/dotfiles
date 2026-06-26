---
# Machine-readable mode block — the SOLE source opsx-gate reads (it never parses
# the prose table below). Keep the table in sync as the human-facing mirror.
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
---

# Review

## Modes

| Mode | Value | Notes |
|---|---|---|
| Scale | L | breaking 3-CLI consolidation + new write surface + 3 bug fixes; Constitution IX (skill edits) |
| Execution Mode | standard | |
| Verification Mode | retained-required | verify.md must be green before archive |
| Debug Mode | standard | |
| Review Status | resolved | two adversarial rounds, converged 0 P0/0 P1 (analyze.md Appendix A) |
| Delegation Mode | single-agent | apply executes inline; only post-impl code-review is delegated to blind reviewers |
| Worktree Mode | worktree-required | |
| Code Review Mode | gating-required | Constitution IX: canonical skill edits → adversarial-multimodel code-review gates archive |
| Loop Max Iterations | 80 | L budget |
| Validation Source Mode | required | `openspec validate --strict` + gate self-syntax + shell/test suites are agent-independent |
| Spec Level | spec-anchored | |
| Model Config | (unset) | session model |

## Diff Base + Worktree locator

**Diff Base SHA:** 184e2556b47d1583a15ac32b1be64822fa913ace
**Worktree Path:** /Users/cartwmic/.local/share/.opsx-worktrees/consolidate-opsx-cli
**Integration Branch:** main

## Manual Adjustments

- Scale L (not M): hard cutover deletes three executables + migrates ~15 caller files across 6 capability specs — breaking, cross-capability, ADR-worthy.
- Code Review Mode gating-required: Constitution IX (canonical skill edits).
- Delegation single-agent: the loop's orphan/takeover failure mode cannot occur when apply runs inline; only blind review is delegated.

## Execution Notes

- 2026-06-25 — propose authored in-session (Scale L); two adversarial review rounds converged 0 P0/0 P1.
