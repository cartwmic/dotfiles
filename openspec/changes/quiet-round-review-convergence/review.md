---
# Machine-readable mode block — the SOLE source opsx gate reads (it never parses
# the prose table below). Keep the table in sync as the human-facing mirror.
scale: M
full_rigor: true
# worktree_mode: (derived when absent: XS/S ⇒ same-tree, M ⇒ worktree-required; uncomment to override)
execution_mode: standard
verification_mode: retained-required
debug_mode: standard
review_status: not-requested
delegation_mode: subagent-required
# code_review_mode: (derived when absent: M ⇒ gating-required, XS/S ⇒ advisory; uncomment to override — an explicit value always wins)
loop_max_iterations: 80
validation_source_mode: required
spec_level: spec-anchored
doneness_mode: required
review_max_rounds: 5
# ── Per-change model pins (resolved by `opsx models`) ──
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
| Scale | M | XS\|S\|M — cross-capability change to the review discipline itself; former-L class under ADR-0025's mapping |
| full_rigor | true | opts this Scale-M change into standalone clarify + blind analyze dispatch + independent blind doneness judge + ADR promotion + adversarial-on-analyze + retrospective |
| Execution Mode | standard | standard\|tdd-preferred\|tdd-required |
| Verification Mode | retained-required | verify.md must be green before archive (review-discipline change; keep the evidence trail) |
| Debug Mode | standard | standard\|systematic-debugging |
| Review Status | not-requested | not-requested\|requested\|findings-received\|resolved |
| Delegation Mode | subagent-required | all review/validation-judgment steps dispatched to blind subagents (openspec-loop mandate) |
| Worktree Mode | derived (absent) | front-matter key COMMENTED OUT ⇒ tier default applies: M ⇒ worktree-required |
| Code Review Mode | derived (gating-required) | front-matter key COMMENTED OUT ⇒ derived fail-closed default: M ⇒ gating-required. Constitution IX also applies (existing-skill edits) |
| Loop Max Iterations | 80 | full_rigor authoring-time default (former L budget) |
| Validation Source Mode | required | agent-independent validation source required at Scale M |
| Doneness Mode | required | independent blind doneness judge (full_rigor dispatch shape, ADR-0026) |
| Spec Level | spec-anchored | deltas anchor to consolidated post-archive capabilities (opsx-adversarial-review, opsx-loop, opsx-cli, opsx-gate-enforcement, opsx-workflow-schema, opsx-skill-integration) |
| Model Config | review pinned | `review_models: [claude-bridge/claude-opus-4-8, claude-bridge/claude-sonnet-5]` — carried from the reviewer set proven on the predecessor change; author/impl unset ⇒ session model |

## Diff Base + Worktree locator

<!--
Captured by apply at worktree creation. `Diff Base SHA` = integration-branch
merge-base, IMMUTABLE for the life of the `opsx/<change>` branch; used by
file-contract diffs, code-review diff base, and opsx gate verdict freshness.
In same-tree mode, Diff Base SHA = pre-apply HEAD and Worktree Path is empty.
-->

**Diff Base SHA:** <empty until apply captures it>
**Worktree Path:** <empty until apply captures it>
**Integration Branch:** main

## Manual Adjustments

- `full_rigor: true` — per frozen intent Scale section (changes the review
  discipline itself; ADR-worthy; cross-capability).
- `review_models` pinned to `[claude-bridge/claude-opus-4-8, claude-bridge/claude-sonnet-5]`
  — the reviewer set in force at the end of simplify-and-parallelize-opsx-workflow
  (gpt-5.5 was usage-limited mid-round there and the user reconfigured to
  sonnet-5); pinning up front avoids a mid-change stability event.
- `verification_mode: retained-required` — stricter than the template default;
  this change edits the gate/review machinery, so the verify evidence trail
  must be retained and green.
- `delegation_mode: subagent-required` — openspec-loop mandates blind subagent
  verdicts for every review/judgment step.
- `review_max_rounds: 5` — explicit default; this change itself specs the
  quiet-round semantics (Q1) but is reviewed under the CURRENT deployed
  protocol.

## Execution Notes

<!-- Transient observations appended during apply. One-line entries when a
non-trivial decision is made mid-task. Durable knowledge → retrospective.md. -->

- 2026-07-03 — review.md authored in-session by the loop orchestrator (gate:
  review.md absent was the earliest failure). Modes trace to intent.md Scale
  section; no user consultation per autonomous drive-to-green directive.

## Scope Expansions

<!-- Evidence-gated widenings (opsx-adversarial-review). intent.md states the
intended scope in PROSE; the loop may widen the scope of WORK only when
evidence shows the widening is REQUIRED to meet the frozen intent's outcomes
(intent MEANING is never edited). One entry per widening; every entry is
surfaced to the user at the decision-audit landing or gate-green. Out-of-scope
findings NOT required for the intent route to follow-ups.md instead. -->

- (none yet)
