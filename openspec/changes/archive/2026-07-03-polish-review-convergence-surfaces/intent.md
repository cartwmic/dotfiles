# Intent — polish-review-convergence-surfaces

Status: explore-frozen

## Intent

Close the in-scope advisory warnings sealed in the archived
`add-opsx-review-convergence` code-review (2026-07-03, findings #4/#6/#8 —
disclosure-round confirmed advisory, promoted here as the successor change):

1. **#4 (P2):** the ledger "repair before archive" negative/recovery obligation
   (`opsx-post-impl-review.round-ledger-sealed-in-code-review`, scenario
   "Missing ledger on a multi-round review is a defect") is specified but not
   restated in any prose surface. Add the red-flag line to the openspec-loop
   skill and the apply-mode reference: a sealed multi-round Verdict with no
   ledger row is a provenance defect — repair the ledger before archive.
2. **#6 (P3):** the code-review template's legacy `## Convergent findings`
   heading misleads against the discipline's no-cross-reviewer-matching ledger
   rule. Rename to `## Findings`, preserving the mandatory gate-manifest check
   comment beneath it.
3. **#8 (P3):** the surface test omits `set -e` intentionally (explicit
   pass/fail counters + final rc); add the clarifying comment.

Extend the surface test to pin the new red-flag line so the addition cannot
silently regress.

## Intended scope (prose)

Exactly these surfaces, all already on main:
- `dot_local/share/agent-harness/canonical/skills/openspec-loop/SKILL.md`
- `dot_local/share/agent-harness/canonical/skills/openspec-apply-change/references/opsx-superpowers-mode.md`
- `dot_local/share/openspec/schemas/opsx-superpowers/templates/code-review.md`
- `tests/opsx-review-convergence/test_review_convergence_surfaces.sh`

No spec-requirement changes: the behaviors are already specified in
`opsx-review-convergence` / `opsx-post-impl-review`; this change makes the
prose surfaces state them. Predecessor finding #5 (task-4.2 `files_allowed`
glob) is change-scoped to the archived predecessor and is NOT pursued.

## Constraints

- No gate/extension code changes; no new tools (Constitution V); canonical
  chezmoi sources only (Constitution II).
- Skill edits at small scale: Scale S with `code_review_mode:
  gating-required` set manually — Constitution IX's multi-model bar is kept by
  mode override rather than by inflating the Scale.
- The convergence discipline (this repo's own review rules) applies to this
  change's review rounds.

## Non-goals

- Gate mechanization of `review_max_rounds` / ledger fields (design D6
  follow-up, separate change).
- Any semantic change to the convergence discipline itself.
- Predecessor finding #7 (treadmill window) — matches frozen baseline wording,
  a note, not a defect.
