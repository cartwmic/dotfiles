---
# Machine-readable mode block — the SOLE source opsx gate reads (it never parses
# the prose table below). Keep the table in sync as the human-facing mirror.
scale: M
# full_rigor: true — owner ruling at intent freeze: this change carries a new
# model-judgment gate artifact + workflow-wide worktree mandate; full L/XL-era
# rigor applies (standalone clarify + blind analyze dispatch, independent blind
# doneness judge, ADR promotion, adversarial-on-analyze, retrospective).
full_rigor: true
# worktree_mode DERIVED by tier when ABSENT: M ⇒ worktree-required. Left absent
# deliberately — this change ABOLISHES the mode; dogfooding the derived
# worktree-required path is the point.
execution_mode: standard
verification_mode: retained-required
debug_mode: standard
review_status: not-requested
delegation_mode: subagent-required
# code_review_mode derived: M ⇒ gating-required (fail-closed). Left absent.
# loop_max_iterations: full_rigor budget (the former L budget).
loop_max_iterations: 80
validation_source_mode: required
spec_level: spec-anchored
doneness_mode: required
# loop_hold: true — orchestrator-settable LANDING signal read by the loop host
# (NOT by opsx gate — gate checks and exit code ignore it). Set it, with a
# non-empty loop_hold_reason, when declaring a terminal landing that awaits a
# human ruling; write it on the INTEGRATION-checkout copy of this file.
# Cleared ONLY by the human named re-arm (/opsx-loop <change>).
# review_max_rounds: 5 — default 5 blind gating rounds (quiet-round semantics).
# review_budget_mode absent ⇒ quiet-round (default).
review_models: [claude-bridge/claude-opus-4-8, claude-bridge/claude-sonnet-5]
---

# Review

<!--
Controlled-vocabulary mode switchboard. The apply instruction reads these modes
and dispatches behavior; opsx gate reads the YAML front-matter above. Override
any mode by setting it (in BOTH the front-matter and this table).
-->

## Modes

| Mode | Value | Notes |
|---|---|---|
| Scale | M | XS\|S\|M — M: worktree-required (derived), gating-required code review (derived) |
| full_rigor | true | Opts Scale-M into the former L/XL extras: standalone clarify.md, blind analyze.md dispatch, independent blind doneness judge, ADR promotion, adversarial-on-analyze, retrospective |
| Execution Mode | standard | standard\|tdd-preferred\|tdd-required |
| Verification Mode | retained-required | verify.md must be green before archive — appropriate for a gate-enforcement change |
| Debug Mode | standard | standard\|systematic-debugging |
| Review Status | not-requested | not-requested\|requested\|findings-received\|resolved |
| Delegation Mode | subagent-required | every review/judgment verdict from a blind subagent (loop directive + Constitution IX) |
| Code Review Mode | derived (absent) | M ⇒ gating-required (fail-closed derived default) |
| Loop Max Iterations | 80 | full_rigor budget (former L) |
| Validation Source Mode | required | agent-independent validation sources required |
| Doneness Mode | required | independent blind doneness judge at full_rigor |
| Spec Level | spec-anchored | |
| Model Config | review_models pinned | claude-bridge/claude-opus-4-8 + claude-bridge/claude-sonnet-5 (proven blind-review pair); author/impl = session model |

## Diff Base + Worktree locator

<!--
Captured by apply at worktree creation. `Diff Base SHA` = integration-branch
merge-base, IMMUTABLE for the life of the `opsx/<change>` branch; used by
file-contract diffs, code-review diff base, and opsx gate verdict freshness.
`Integration Branch` ships as the `<detected-at-capture>` sentinel and is FILLED
by apply via the deterministic resolver (committed locator > origin/HEAD >
main > master).
-->

**Diff Base SHA:** 40d6ff09a3169584bf03ce20567306031d4c2e7c
**Worktree Path:** /Users/cartwmic/.local/share/chezmoi--opsx-add-opsx-design-fidelity-gate
**Integration Branch:** main

## Manual Adjustments

- `full_rigor: true` — owner ruling at intent freeze (2026-07-05): new model-judgment gate artifact + workflow-wide worktree mandate warrants the full rigor stack.
- `verification_mode: retained-required` — gate-enforcement change; verify.md must be green before archive.
- `delegation_mode: subagent-required` — autonomous loop with blind subagent verdicts for every judgment step.
- `loop_max_iterations: 80` — full_rigor authoring-time default.
- `review_models` pinned to the proven blind-review pair (opus-4-8 + sonnet-5).

## Execution Notes

<!-- Transient observations appended during apply. -->

## Scope Expansions

<!-- Evidence-gated widenings (opsx-adversarial-review). -->

## Fidelity Round Ledger

<!-- Append-only; orchestrator-sealed. A design-fidelity.md re-seal never
removes rows. Valve counts consecutive `violated` rows not separated by a
`waived` or `delivered` row. -->

| Round | Fidelity | Per-judge verdicts | Attested HEAD |
|---|---|---|---|
| 1 | violated | opus: violated; sonnet: violated | 116c611f0e6e860ed7e0afe92023db377587c1ed |
| 2 | delivered | opus: delivered; sonnet: delivered | 6947eca6d2c6581e09aa6f8f9989ad370c65843f |
| 3 | violated | opus: delivered; sonnet: violated (worst-of) | 4367c4771a884307317aa4acb750ccca02d187d4 |
| 4 | delivered | opus: delivered; sonnet: delivered | 00e50f7ed48fcf29d99fbefd053c6825003cd25b |
| 5 | violated | opus: delivered; sonnet: violated (worst-of) | 548e735aa63f0f831b7051a517a79a97e9cd2047 |
| 6 | delivered | opus: delivered; sonnet: delivered | 3ed7909c3f15d862c6c260b92f73f91c21da6be1 |
| 7 | violated | opus: delivered; sonnet: violated (worst-of) | 185b613be2c932d00996350ddcba017b4da601b8 |
| 8 | violated | opus: delivered; sonnet: violated (worst-of) | 90e207f073f374f3b653425da4c8b38bf46e67f5 |
| 9 | delivered | opus: delivered; sonnet: delivered | 2ba9951b0808320e34797bf108e2ef1d43408e69 |

Note (dogfood): rows 7–8 are two consecutive `violated` — the valve threshold.
The valve mechanism ships WITH this change (not yet live); the R8 design/delta
fixes plus the R9 full-sweep `delivered` resolved the streak before any
landing routing. Recorded for honesty, not as a waiver.
