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
loop_max_iterations: 40
validation_source_mode: required
spec_level: spec-anchored
doneness_mode: required
---

<!-- authored: in-session -->

# Review

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
| Delegation Mode | single-agent | single-agent\|subagent-eligible\|subagent-required — dispatch via the subagent-dispatch capability hook (pi-subagents is the pi adapter) |
| Worktree Mode | derived (absent) | same-tree\|worktree-eligible\|worktree-required — default DERIVED by tier when absent (XS/S ⇒ same-tree, M ⇒ worktree-required); the front-matter ships the key COMMENTED OUT so the tier default applies; an explicit value always wins |
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
In same-tree mode, Diff Base SHA = pre-apply HEAD and Worktree Path is empty.
-->

**Diff Base SHA:** 25f6f22906c0d7fa58f4f863be99f6630bf7a04a
**Worktree Path:** /Users/cartwmic/.local/share/chezmoi--opsx-ntfy-harpoon-jump
**Integration Branch:** main

## Manual Adjustments

<!-- Author-driven overrides to defaults. One bullet per non-default value with
rationale. Keep the front-matter, the table, and these notes consistent. -->

- Scale M (full_rigor false) chosen to match the sibling `ntfy-harpoon-jump`
  slices in the `harpoon` and `termux-app` repos, both of which shipped GATE-PASS
  at Scale M / full_rigor false on 2026-07-04. This chezmoi slice (remote notify
  wrapper script + phone ControlMaster snippet + idempotent install) is
  comparable in surface, and chezmoi's opsx-superpowers gate + constitution
  warrant the M-tier worktree + gating code-review + doneness discipline.

## Execution Notes

<!-- Transient observations appended during apply. One-line entries when a
non-trivial decision is made mid-task. Durable knowledge → retrospective.md. -->

- 2026-07-04 — review.md authored in-session to satisfy earliest GATE-FAIL (Scale source).
- 2026-07-04 — worktree ensured (opsx/ntfy-harpoon-jump); Diff Base SHA 25f6f22 captured.
- 2026-07-04 — round-1 blind review (opus pass, gpt fail: 2 P1). Both P1 confirmed
  and fixed at HEAD 6afcd61: jump payload moved from non-propagated custom X-*
  headers onto the ntfy `Click` deep link; wrapper now reads the env-sourced
  remote host (`JUMP_SSH_HOST`) the spec requires.
- 2026-07-04 — rounds 2-4 (gpt) chased pre-existing-ControlMaster detection; each
  heuristic spawned a new edge. Resolved at HEAD 741371b by simplifying to a
  sentinel-only idempotence guard and NARROWING the spec's second idempotence
  scenario to the managed block (intent scope = Constitution IV "no-op when
  already applied by this script"). Unmanaged-config detection routed to
  follow-ups.md (P3, out of scope). opus rated it P2/P3 every round.
- 2026-07-04 — Cross-slice contract (assumption): the tap deep-link scheme is
  `termux-harpoon-jump://jump` by default, overridable via `JUMP_DEEPLINK_BASE`,
  and MUST match the already-shipped termux-app fork's registered handler. Left
  configurable rather than hard-coding a guess at the fork's exact scheme.

## Scope Expansions

<!-- Evidence-gated widenings (opsx-adversarial-review). intent.md states the
intended scope in PROSE; the loop may widen the scope of WORK only when
evidence shows the widening is REQUIRED to meet the frozen intent's outcomes
(intent MEANING is never edited). One entry per widening; every entry is
surfaced to the user at the decision-audit landing or gate-green. Out-of-scope
findings NOT required for the intent route to follow-ups.md instead. -->

- (none yet)
