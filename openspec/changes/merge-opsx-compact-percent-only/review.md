---
# Machine-readable mode block — the SOLE source opsx gate reads (it never parses
# the prose table below). Keep the table in sync as the human-facing mirror.
scale: M
full_rigor: false
execution_mode: standard
verification_mode: retained-recommended
debug_mode: standard
review_status: not-requested
delegation_mode: single-agent
# code_review_mode: derived when absent — M ⇒ gating-required
loop_max_iterations: 40
validation_source_mode: required
spec_level: spec-anchored
doneness_mode: required
---

# Review

## Modes

| Mode | Value | Notes |
|---|---|---|
| Scale | M | XS\|S\|M — cross-file change to a single capability area (compaction guard config), plus a new spec capability |
| full_rigor | false | No cross-capability/breaking/migration concerns; frozen intent sets full_rigor: false |
| Execution Mode | standard | standard |
| Verification Mode | retained-recommended | retained-recommended |
| Debug Mode | standard | standard |
| Review Status | not-requested | not-requested |
| Delegation Mode | single-agent | single-agent |
| Code Review Mode | derived (absent) | M ⇒ gating-required (derived, fail-closed) |
| Loop Max Iterations | 40 | authoring-time default for Scale M |
| Validation Source Mode | required | bun test suite in dot_pi/agent/extensions/opsx-loop is the agent-independent validation source |
| Doneness Mode | required | default at Scale ≥ M; plain-M combined dispatch (rides code-review, designated first review model) |
| Spec Level | spec-anchored | spec-anchored |
| Model Config | (unset) | roles resolve via `opsx models`; session model fallback |

## Diff Base + Worktree locator

**Diff Base SHA:** 2d0bcd1355f5b5e7bd37939013dd88f0f4437b71
**Worktree Path:** /Users/cartwmic/.local/share/chezmoi-opsx-merge-compact
**Integration Branch:** main

## Manual Adjustments

- Scale M with full_rigor false — set per the frozen intent.md (cross-file, single
  capability: helpers.ts + index.ts + tests + new compaction-guard spec capability).

## Execution Notes

- 2026-07-09 — review.md authored in-session (loop turn 1); Scale/full_rigor taken
  verbatim from frozen intent.md constraints.
- 2026-07-09 — worktree created on `opsx/merge-opsx-compact-percent-only`; Diff Base
  = merge-base(main, HEAD) at creation; integration branch resolved to `main`
  (repo-local, no divergent origin/HEAD).

## Scope Expansions

<!-- Evidence-gated widenings. One entry per widening; surfaced at the
decision-audit landing or gate-green. -->

- 2026-07-09 — updated stale assertion in
  `tests/opsx-review-convergence/test_review_convergence_surfaces.sh` (retired
  literal "gating-required at every tier" → current 3-tier doctrine
  "`gating-required` at Scale M" + fail-closed-derivation check) — evidence: gate
  check `validation-opsx-review-convergence-surface-tests` fails on unmodified
  main (pre-existing red introduced by 3928abb, which reworded the loop skill
  without updating this surface test); the frozen intent's gate-green outcome is
  unreachable while a required repo validator is red, and the replacement
  assertion matches spec-of-record `opsx-adversarial-review` switchboard-default
  (M ⇒ gating-required derived fail-closed, advisory below M) rather than
  weakening coverage.

## Fidelity Round Ledger

| Round | Fidelity | Per-judge verdicts | Attested HEAD |
|---|---|---|---|
