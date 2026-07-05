# Code Review

<!--
Filled from the shipped template
~/.local/share/openspec/schemas/opsx-superpowers/templates/code-review.md
(Q3 discipline). Reviewer content authored by the blind subagents (outputs
/tmp/hrp-cr-r1-{opus,sonnet}.md); orchestrator seals ledger + verdict fields
only. Constitution IX applies (existing-skill edits) => multi-model
adversarial review even though Scale S derives Code Review Mode advisory.
-->

**Change:** harden-opsx-repo-portability
**Verdict:** pass
**review_mode:** adversarial-multimodel
**reviewer-provenance:** pi-subagents delegate dispatch — claude-bridge/claude-opus-4-8 (/tmp/hrp-cr-r1-opus.md) + claude-bridge/claude-sonnet-5 (/tmp/hrp-cr-r1-sonnet.md), blind fresh-context, round 1
**Diff Base SHA:** a8c52af74a7ec8c81ce8367e2a124b433164bd3d
**Reviewed Range:** a8c52af..3c3f666
**Baseline:** intent.md (frozen) + proposal + specs delta ACs + clarify + plan + tasks status
**Generated:** 2026-07-05

## Verdict contract

<!--
Baseline-bounded contract (opsx-adversarial-review): FAIL only for (a) a
frozen-baseline violation — intent.md, delta ACs, design decisions,
constitution/domain — or (b) an objective correctness/security defect.
P0 baseline violation/critical · P1 must-fix in contract · P2 should-fix
advisory · P3 nit. Verdict: pass ⇔ no open P0/P1; open P2/P3 recorded as
warnings, never force another round. Embedded verbatim in both dispatch
prompts.
-->

## Round ledger

| Round | Mode | P0 | P1 | P2 | P3 | Per-reviewer verdicts | Reviewed HEAD |
|---|---|---|---|---|---|---|---|
| 1 | blind adversarial (2-model) | 0 | 0 | 1 | 2 | opus-4-8: pass · sonnet-5: pass | 781ecb5 |

<!--
Counts = max across reviewers per severity, no cross-reviewer finding matching.
Quiet round at round 1 (0 new P0/P1 from BOTH reviewers) => seal pass, stop
rounds (quiet-round default, review_budget_mode absent). 1/5 rounds used.
Same-tree note: reviewed range interleaves concurrent ntfy-harpoon-jump fleet
commits (ADR-0024 visibility-over-locking); both reviewers instructed to judge
only this change's file set.
-->

## Resolution of round-1 advisories (fixed same-turn, post-seal-range advance)

- R1-O1 (P2, opus) capture-time `Integration Branch` fill used current branch,
  not resolver steps 2-4 — FIXED at 3c3f666: `opsx worktree ensure` defaults
  IBRANCH via `opsx_integration_branch "$ROOT"` (no change arg), current-branch
  + detached-HEAD guard retained as fallback; explicit --integration-branch
  still wins.
- R1-S1 (P2, sonnet) two in-script comments still asserted literal `main`
  (status header, multi-dir detector header) contradicting intent D2's
  "must not contradict" clause — FIXED at 3c3f666: resolved-branch wording.
- R1-O2 (P3, opus) dup-ADR/multi-dir comment `..main` literal — same fix.

## Open warnings (non-gating, follow-up seeds)

- R1-O3/S-note (P3): resolver placeholder guard treats any `<`-prefixed locator
  value as placeholder, broader than the exact `<detected-at-capture>` sentinel
  clarify C1 specifies. Deliberate fail-safe (legacy `<empty until ...>`
  placeholders; `<` never begins a real branch); documented in review.md
  Execution Notes. Seed: tighten spec wording or guard in a successor hygiene
  change.

## Validator results (both reviewers, independently)

bash -n clean · opsx-cli 67/0 · opsx-gate 128/0 · opsx-models 34/0 ·
surfaces 152/0 · author-marker 4/0 · bun opsx-loop 60/0 (108 expects) ·
openspec validate change --strict valid · --specs --strict 12/12.
