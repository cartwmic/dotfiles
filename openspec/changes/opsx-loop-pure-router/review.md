---
# Machine-readable mode block — the SOLE source opsx gate reads (it never parses
# the prose table below). Keep the table in sync as the human-facing mirror.
scale: M
# full_rigor: true — owner ruling at intent freeze (2026-07-15): pure-router
# armed tool surface is a breaking UX change across opsx-loop + skill-integration;
# warrants former L/XL extras (standalone clarify, blind analyze, independent
# doneness judge, ADR promotion, adversarial-on-analyze, retrospective).
full_rigor: true
# Worktree execution is the ONLY model at every Scale (XS included) — there is
# no worktree-selection mode and no key to set: apply always creates an isolated
# `git worktree` on `opsx/<change>`. A worktree-selection key is rejected
# fail-closed by the gate (delete the key remedy).
execution_mode: standard
verification_mode: retained-recommended
debug_mode: standard
review_status: not-requested
delegation_mode: subagent-required
# code_review_mode: (derived when absent: M ⇒ gating-required, XS/S ⇒ advisory)
loop_max_iterations: 80
validation_source_mode: required
spec_level: spec-anchored
doneness_mode: required
# Change-scoped role pins (Constitution IX skill edits → ≥2 review models).
impl_model: cursor/composer-2.5:high
author_in_session: true
review_models:
  - anthropic/claude-opus-4-8:medium
  - cursor/gpt-5-6-terra@1m:high
---

# Review

<!-- authored: in-session -->

## Modes

| Mode | Value | Notes |
|---|---|---|
| Scale | M | XS\|S\|M — skills author per Scale. Out-of-range fails closed |
| full_rigor | true | Opts Scale-M into former L/XL extras: standalone clarify, blind analyze, independent doneness, ADR, adversarial-on-analyze, retrospective |
| Execution Mode | standard | standard\|tdd-preferred\|tdd-required |
| Verification Mode | retained-recommended | inline-only\|retained-recommended\|retained-required |
| Debug Mode | standard | standard\|systematic-debugging |
| Review Status | not-requested | not-requested\|requested\|findings-received\|resolved |
| Delegation Mode | subagent-required | Constitution IX skill edits → blind multimodel review; full_rigor judgments via blind subagents |
| Code Review Mode | derived (absent) | M ⇒ gating-required (fail-closed) |
| Loop Max Iterations | 80 | full_rigor authoring-time default |
| Validation Source Mode | required | agent-independent tests required (armed mute + bookkeep matrix) |
| Doneness Mode | required | independent blind doneness judge at full_rigor |
| Spec Level | spec-anchored | default |
| Model Config | review_models + impl pinned | env-resolved pair; author_in_session true for propose-phase in-session authoring |

## Diff Base + Worktree locator

<!--
Captured by apply at worktree creation. `Diff Base SHA` = integration-branch
merge-base, IMMUTABLE for the life of the `opsx/<change>` branch.
`Integration Branch` filled by apply via deterministic resolver.
-->

**Diff Base SHA:** 318b6d8d7635cec79240a497f6857346e2103310
**Worktree Path:** /Users/mcartwright/.local/share/chezmoi--opsx-opsx-loop-pure-router
**Integration Branch:** main

## Manual Adjustments

- Scale M, `full_rigor: true` per frozen intent.md (pure-router armed tool surface;
  cross-capability loop + skill-integration; breaking armed authoring UX).
- `delegation_mode: subagent-required` — Scale M gating code review + Constitution IX
  skill edits + full_rigor blind analyze/doneness.
- `code_review_mode` left absent (derives to gating-required at M).
- `loop_max_iterations: 80` — full_rigor authoring-time default.
- Spec Level: spec-anchored (default).
- `review_models` pinned to env-resolved pair (opus-4-8:medium + gpt-5-6-terra@1m:high);
  `impl_model: cursor/composer-2.5:high`; `author_in_session: true` for propose-phase
  (armed override is THIS change's outcome, not yet live).

## Execution Notes

- 2026-07-15 — authored review.md switchboard from frozen intent (Scale M,
  full_rigor: true, core envelope: mute edit/write + opsx_bookkeep + armed author
  override; shell residual accepted as Non-goal).
- 2026-07-15 — design-fidelity R1 violated (worktree carry-forward + empty
  set-hold / multi-review / provider gaps); design patched (`e684ae4` D7 + D2/D4);
  R2 full-sweep both judges delivered at HEAD `e684ae4361d1132f05fa3b1dbafcd1b0ef7030e9`.

## Scope Expansions

<!-- Evidence-gated widenings (opsx-adversarial-review). -->

## Fidelity Round Ledger

<!--
Append-only orchestrator bookkeeping for design-fidelity rounds.
-->

| Round | Fidelity | Per-judge verdicts | Attested HEAD |
|---|---|---|---|
| R1 | violated | Task×2: violated (not-covered worktree + gaps) | e63443f73e481741c0a5a79e69ca12824e102d3a |
| R2 | delivered | Task×2: delivered (28/28 entailed) | e684ae4361d1132f05fa3b1dbafcd1b0ef7030e9 |
