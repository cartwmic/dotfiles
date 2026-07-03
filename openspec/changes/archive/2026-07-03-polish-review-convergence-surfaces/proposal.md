<!-- authored: in-session -->

## Why

The archived `add-opsx-review-convergence` change sealed three in-scope
advisory warnings (code-review findings #4/#6/#8, disclosure-round confirmed):
the ledger-repair recovery obligation is specified but stated on no prose
surface; the code-review template's legacy `## Convergent findings` heading
contradicts the discipline's no-cross-reviewer-matching rule; and the surface
test's intentional `set -e` omission is uncommented. Advisory findings promote
to a successor change — this is that change.

## What Changes

- openspec-loop SKILL.md + apply-mode reference gain the red-flag line: a
  sealed multi-round Verdict with no ledger row is a provenance defect —
  repair the ledger before archive.
- code-review.md template heading `## Convergent findings` → `## Findings`
  (gate-manifest check comment preserved).
- Surface test: comment documenting the intentional `set -e` omission; new
  assertions pinning the red-flag line and the heading.

## Capabilities

### New Capabilities
- (none)

### Modified Capabilities
- `opsx-review-convergence`: adds a prose-surface-fidelity requirement — the
  discipline's prose surfaces state the ledger-repair recovery obligation and
  do not imply cross-reviewer finding matching.

## Impact

- **Files:** `dot_local/share/agent-harness/canonical/skills/openspec-loop/SKILL.md`,
  `dot_local/share/agent-harness/canonical/skills/openspec-apply-change/references/opsx-superpowers-mode.md`,
  `dot_local/share/openspec/schemas/opsx-superpowers/templates/code-review.md`,
  `tests/opsx-review-convergence/test_review_convergence_surfaces.sh`
- No gate/extension code, no spec-semantics changes, no repo migration.
- Predecessor finding #5 (archived change's task glob) not pursued — change-scoped.
