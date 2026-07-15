---
# Machine-readable mode block — the SOLE source opsx gate reads (it never parses
# the prose table below). Keep the table in sync as the human-facing mirror.
scale: M
# full_rigor: false — boolean (default false). true opts a Scale-M change into the
# former L/XL extras: standalone clarify.md, blind analyze.md dispatch, an
# independently dispatched blind doneness judge, ADR promotion, adversarial-on-
# analyze, and a pre-archive retrospective. A Scale outside XS|S|M, or a
# non-boolean full_rigor, FAILS CLOSED (never a silent permissive default).
full_rigor: false
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
loop_max_iterations: 40
validation_source_mode: required
spec_level: spec-anchored
doneness_mode: required
# Change-scoped role pins (user-layer review unset; gating needs ≥2 models).
impl_model: cursor/composer-2.5
author_in_session: true
review_models:
  - anthropic/claude-sonnet-5
  - anthropic/claude-opus-4-8
---

# Review

<!-- authored: in-session -->

## Modes

| Mode | Value | Notes |
|---|---|---|
| Scale | M | XS\|S\|M — skills author per Scale. Out-of-range fails closed |
| full_rigor | false | false\|true — plain M: clarify-in-proposal, deterministic analyze |
| Execution Mode | standard | standard\|tdd-preferred\|tdd-required |
| Verification Mode | retained-recommended | inline-only\|retained-recommended\|retained-required |
| Debug Mode | standard | standard\|systematic-debugging |
| Review Status | not-requested | not-requested\|requested\|findings-received\|resolved |
| Delegation Mode | subagent-required | Constitution IX skill edits → blind multimodel review |
| Code Review Mode | derived (absent) | M ⇒ gating-required (fail-closed) |
| Loop Max Iterations | 40 | authoring-time M default |
| Validation Source Mode | required | agent-independent tests required |
| Doneness Mode | required | sealed doneness.md after code-review |
| Spec Level | spec-anchored | default |
| Model Config | review_models + impl pinned | same pair as prior role-dispatch |

## Diff Base + Worktree locator

<!--
Captured by apply at worktree creation. `Diff Base SHA` = integration-branch
merge-base, IMMUTABLE for the life of the `opsx/<change>` branch.
`Integration Branch` filled by apply via deterministic resolver.
-->

**Diff Base SHA:** bd976b5774628621a38a28c347ac41910ca3dd0b
**Worktree Path:** /Users/mcartwright/.local/share/chezmoi--opsx-opsx-dispatch-transparent
**Integration Branch:** main

## Manual Adjustments

- Scale M, `full_rigor: false` per frozen intent.md (transparent shim +
  parallel fan-out; not a cross-capability migration).
- `delegation_mode: subagent-required` — Scale M gating code review +
  Constitution IX skill edits.
- `code_review_mode` left absent (derives to gating-required at M).
- Spec Level: spec-anchored (default).
- `review_models` pinned (sonnet + opus); `impl_model: cursor/composer-2.5`;
  `author_in_session: true`.

## Execution Notes

- 2026-07-14 — R1 voided: integration HEAD moved mid-window with sibling `opsx-loop-models-interactive` archive (touched `dot_pi/agent/extensions/opsx-loop/` + `openspec/specs/opsx-loop/`). Worktree HEAD unchanged; verdicts INVALID per read-only-round-window. Landing P1 fixes then rebase + R2 freshness.

- Plain-M: no standalone clarify/design/analyze; decisions in intent +
  proposal Open Questions.
- Supersedes sequential review fan-out from archived
  `opsx-loop-role-dispatch`; bind/mute/unset-refuse retained.
- Sibling `opsx-loop-models-interactive` out of scope.

## Scope Expansions

<!-- Append-only. Empty until a finding requires widening. -->

## Fidelity Round Ledger

| Round | Fidelity | Per-judge verdicts | Attested HEAD |
|---|---|---|---|
| (none — no design.md) | — | — | — |
