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
# `git worktree` on `opsx/<change>`. A worktree-selection key here is rejected
# fail-closed by the gate (delete the key remedy).
execution_mode: standard
verification_mode: retained-recommended
debug_mode: standard
review_status: not-requested
delegation_mode: subagent-required
# code_review_mode: (derived when absent: M ⇒ gating-required, XS/S ⇒ advisory; uncomment to override — an explicit value always wins)
# loop_max_iterations authoring-time defaults keyed by tier: XS=10, S=20, M=40,
# full_rigor=80 (the former L budget). The value is written here at authoring
# time; the loop runtime reads it verbatim.
loop_max_iterations: 40
validation_source_mode: required
spec_level: spec-anchored
doneness_mode: required
# review_max_rounds: 5
# review_budget_mode: quiet-round
---

# Review

<!-- authored: in-session -->

<!--
Controlled-vocabulary mode switchboard. The apply instruction reads these modes
and dispatches behavior; opsx gate reads the YAML front-matter above. Override
any mode by setting it (in BOTH the front-matter and this table).
-->

## Modes

| Mode | Value | Notes |
|---|---|---|
| Scale | M | XS\|S\|M — skills author per Scale (graph is static; gating lives in the skills + opsx gate). Out-of-range fails closed |
| full_rigor | false | false\|true — true opts Scale-M into the former L/XL extras (standalone clarify+analyze, independent doneness judge, ADR promotion, adversarial-on-analyze, retrospective) |
| Execution Mode | standard | standard\|tdd-preferred\|tdd-required |
| Verification Mode | retained-recommended | inline-only\|retained-recommended\|retained-required — retained-required forces verify.md green before archive |
| Debug Mode | standard | standard\|systematic-debugging |
| Review Status | not-requested | not-requested\|requested\|findings-received\|resolved |
| Delegation Mode | subagent-required | single-agent\|subagent-eligible\|subagent-required — dispatch via the subagent-dispatch capability hook (pi-subagents is the pi adapter) |
| Code Review Mode | derived (absent) | none\|advisory\|gating-required — default DERIVED when absent: M ⇒ gating-required, XS/S ⇒ advisory (fail-closed); an explicit value always wins; gating-required blocks archive on code-review.md Verdict |
| Loop Max Iterations | 40 | iteration budget; mapped onto the loop runtime turn budget. Authoring-time defaults XS=10, S=20, M=40, full_rigor=80 |
| Validation Source Mode | required | required\|waived — waived (with rationale) lets Scale ≥ M pass with no agent-independent validation source |
| Doneness Mode | required | required\|waived — default required at Scale ≥ M; a `waived` value needs a non-empty `doneness_waiver_rationale` (bare waiver fails). Gate reads a sealed `doneness.md` verdict (see templates/doneness.md) |
| Spec Level | spec-anchored | spec-anchored\|spec-first\|spec-as-source (warning if last) |
| Model Config | (unset) | optional `author_model`/`review_models`/`impl_model`/`author_in_session` + `provider`/`*_provider` front-matter keys, resolved by `opsx models`; unset ⇒ session model |

## Diff Base + Worktree locator

<!--
Captured by apply at worktree creation. `Diff Base SHA` = integration-branch
merge-base, IMMUTABLE for the life of the `opsx/<change>` branch; used by
file-contract diffs, code-review diff base, and opsx gate verdict freshness.
Worktree execution is the only model at every Scale, so `Worktree Path` is
always filled by apply (never empty) — there is no alternate diff-base source.
`Integration Branch` ships as the `<detected-at-capture>` sentinel and is FILLED
by apply via the deterministic resolver (committed locator > origin/HEAD >
main > master) — never assume a hardcoded literal (opsx-workflow-schema.
integration-branch-locator-default-detected).
-->

**Diff Base SHA:** <empty until apply captures it>
**Worktree Path:** <empty until apply captures it>
**Integration Branch:** <detected-at-capture>

## Manual Adjustments

<!-- Author-driven overrides to defaults. One bullet per non-default value with
rationale. Keep the front-matter, the table, and these notes consistent. -->

- Scale M, `full_rigor: false` per frozen intent.md (typical feature: interactive
  `opsx models set` UX + multi-review write fix; not cross-capability migration).
- `delegation_mode: subagent-required` — Scale M gating code review needs blind
  subagent dispatch.
- `code_review_mode` left absent (derives to gating-required at M, fail-closed).
- Spec Level: spec-anchored (default).

## Execution Notes

<!-- Transient observations appended during apply. One-line entries when a
non-trivial decision is made mid-task. Durable knowledge → retrospective.md. -->

- 2026-07-14 — review.md authored from schema template at loop start
  (openspec-loop); Scale/modes from frozen intent.md.
- 2026-07-14 — Plain-M propose: proposal + specs (opsx-cli, opsx-model-config)
  + tasks + plan; clarify/design/analyze skipped (open questions in proposal;
  design decision-gated skipped — UX locked in intent).

## Scope Expansions

<!-- Evidence-gated widenings (opsx-adversarial-review). intent.md states the
intended scope in PROSE; the loop may widen the scope of WORK only when
evidence shows the widening is REQUIRED to meet the frozen intent's outcomes
(intent MEANING is never edited). One entry per widening; every entry is
surfaced to the user at the decision-audit landing or gate-green. Out-of-scope
findings NOT required for the intent route to follow-ups.md instead. -->

## Fidelity Round Ledger

<!--
Append-only orchestrator bookkeeping (opsx-adversarial-review Orchestrator Round
Ledger — the design-fidelity host). Present at EVERY Scale and available BEFORE
worktree creation. One row per sealed design-fidelity judgment round (any overall
verdict) AND per human-waiver ruling (`Fidelity` = `waived`, Per-judge verdicts =
the ruling reference). Sealing or re-sealing design-fidelity.md NEVER removes or
rewrites a prior row — a full-sweep re-seal overwrites the artifact, never this
ledger, so the escalation valve's count survives re-seals and fresh sessions.
The valve counts CONSECUTIVE `violated` rows NOT separated by a `waived` or
`delivered` row: two consecutive `violated` rows route to the decision-audit
landing for a human ruling (no per-row cross-round matching, consistent with the
full-sweep rule); a `waived`/`delivered` row breaks the streak so a resolved
streak never re-fires against a superseded round. `Attested HEAD` is the
attested integration-checkout HEAD of that round.
-->

| Round | Fidelity | Per-judge verdicts | Attested HEAD |
|---|---|---|---|
| 1 | <delivered \| violated \| waived> | <judge:verdict … \| ruling ref> | <40-hex integration-checkout HEAD> |
