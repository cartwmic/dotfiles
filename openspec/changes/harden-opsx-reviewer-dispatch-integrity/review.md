---
# Machine-readable mode block — the SOLE source opsx gate reads (it never parses
# the prose table below). Keep the table in sync as the human-facing mirror.
scale: S
# full_rigor: false — boolean (default false). true opts a Scale-M change into the
# former L/XL extras: standalone clarify.md, blind analyze.md dispatch, an
# independently dispatched blind doneness judge, ADR promotion, adversarial-on-
# analyze, and a pre-archive retrospective. A Scale outside XS|S|M, or a
# non-boolean full_rigor, FAILS CLOSED (never a silent permissive default).
full_rigor: false
# worktree_mode DERIVED by tier when ABSENT: XS/S ⇒ same-tree, M ⇒
# worktree-required. An explicit value here ALWAYS wins over the tier default.
# worktree_mode: (derived when absent: XS/S ⇒ same-tree, M ⇒ worktree-required; uncomment to override)
execution_mode: standard
verification_mode: retained-required
debug_mode: standard
review_status: not-requested
delegation_mode: single-agent
# Constitution IX override: this change edits the opsx CLI, shipped schema
# templates, and existing skills — existing-skill edits require adversarial
# multi-model gating code review even below Scale M.
code_review_mode: gating-required
loop_max_iterations: 20
validation_source_mode: required
spec_level: spec-anchored
doneness_mode: required
# loop_hold: true — orchestrator-settable LANDING signal read by the loop host
# (NOT by opsx gate — gate checks and exit code ignore it). Set it, with a
# non-empty loop_hold_reason, when declaring a terminal landing that awaits a
# human ruling (decision audit, presented green report, blocked state); write it
# on the INTEGRATION-checkout copy of this file. Cleared ONLY by the human named
# re-arm (/opsx-loop <change>) — agents never clear it. A true value with an
# empty reason still holds (fail-safe).
# loop_hold_reason: <why the loop landed — e.g. "decision audit in code-review.md round 4">
# review_max_rounds: 5 — budget of BLIND gating review rounds per change
# (opsx-adversarial-review). Absent/invalid ⇒ consumers apply the default 5.
review_models: [claude-bridge/claude-opus-4-8, claude-bridge/claude-sonnet-5]
provider: claude-bridge
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
| Scale | S | XS\|S\|M — skills author per Scale (graph is static; gating lives in the skills + opsx gate). Out-of-range fails closed |
| full_rigor | false | false\|true — true opts Scale-M into the former L/XL extras (standalone clarify+analyze, independent doneness judge, ADR promotion, adversarial-on-analyze, retrospective) |
| Execution Mode | standard | standard\|tdd-preferred\|tdd-required |
| Verification Mode | retained-required | inline-only\|retained-recommended\|retained-required — retained-required forces verify.md green before archive |
| Debug Mode | standard | standard\|systematic-debugging |
| Review Status | not-requested | not-requested\|requested\|findings-received\|resolved |
| Delegation Mode | single-agent | single-agent\|subagent-eligible\|subagent-required — dispatch via the subagent-dispatch capability hook (pi-subagents is the pi adapter) |
| Worktree Mode | derived (absent) | same-tree\|worktree-eligible\|worktree-required — default DERIVED by tier when absent (XS/S ⇒ same-tree, M ⇒ worktree-required); the front-matter ships the key COMMENTED OUT so the tier default applies; an explicit value always wins |
| Code Review Mode | gating-required | none\|advisory\|gating-required — EXPLICIT override (Constitution IX: existing-skill + CLI + template edits); gating-required blocks archive on code-review.md Verdict |
| Loop Max Iterations | 20 | iteration budget; mapped onto the loop runtime turn budget. Authoring-time defaults XS=10, S=20, M=40, full_rigor=80 |
| Validation Source Mode | required | required\|waived — waived (with rationale) lets Scale ≥ M pass with no agent-independent validation source |
| Doneness Mode | required | required\|waived — default required at Scale ≥ M; a `waived` value needs a non-empty `doneness_waiver_rationale` (bare waiver fails). Gate reads a sealed `doneness.md` verdict (see templates/doneness.md) |
| Spec Level | spec-anchored | spec-anchored\|spec-first\|spec-as-source (warning if last) |
| Model Config | review_models pinned | claude-bridge/claude-opus-4-8 + claude-bridge/claude-sonnet-5 (proven reviewer set; gpt-5.5 excluded — wrong-tree/read-only violations this change exists to detect) |

## Diff Base + Worktree locator

<!--
Captured by apply at worktree creation. `Diff Base SHA` = integration-branch
merge-base, IMMUTABLE for the life of the `opsx/<change>` branch; used by
file-contract diffs, code-review diff base, and opsx gate verdict freshness.
In same-tree mode, Diff Base SHA = pre-apply HEAD and Worktree Path is empty.
`Integration Branch` ships as the `<detected-at-capture>` sentinel and is FILLED
by apply via the deterministic resolver (committed locator > origin/HEAD >
main > master) — never assume a hardcoded literal (opsx-workflow-schema.
integration-branch-locator-default-detected).
-->

**Diff Base SHA:** ff5a8606923247f37f0af87c691cc90b989aa25a
**Worktree Path:**
**Integration Branch:** main

## Manual Adjustments

<!-- Author-driven overrides to defaults. One bullet per non-default value with
rationale. Keep the front-matter, the table, and these notes consistent. -->

- `code_review_mode: gating-required` (tier default at S is advisory) — Constitution IX: this change edits the opsx CLI (`executable_opsx`), shipped verdict templates, and existing skills (openspec-loop, openspec-apply-change reference), which require adversarial multi-model gating code review.
- `verification_mode: retained-required` (template default retained-recommended) — CLI/gate behavior changes warrant a retained verify.md hard gate.
- `review_models` pinned to `claude-bridge/claude-opus-4-8` + `claude-bridge/claude-sonnet-5` — proven reliable pair; the gpt-5.5 slot exhibited the exact wrong-tree/read-only failures this change hardens against (session 019f2d9f, oxide-clone).

## Execution Notes

<!-- Transient observations appended during apply. One-line entries when a
non-trivial decision is made mid-task. Durable knowledge → retrospective.md. -->

- 2026-07-05 — review.md authored from shipped template; Scale S, same-tree derived.
- 2026-07-05 — impl: gate attestation checks (CR + full_rigor doneness), template fields + preamble, skill prose (loop + apply ref), 12 new gate cases + 16 surface pins. Suites: gate 140, convergence 168, cli 67, models 34, marker 4, bun 60 — all green.

## Scope Expansions

<!-- Evidence-gated widenings (opsx-adversarial-review). intent.md states the
intended scope in PROSE; the loop may widen the scope of WORK only when
evidence shows the widening is REQUIRED to meet the frozen intent's outcomes
(intent MEANING is never edited). One entry per widening; every entry is
surfaced to the user at the decision-audit landing or gate-green. Out-of-scope
findings NOT required for the intent route to follow-ups.md instead. -->

- (none)
