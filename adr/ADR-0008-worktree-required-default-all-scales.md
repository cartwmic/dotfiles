# ADR-0008: Worktree-required is the default for all Scales

**Status:** Accepted
**Date:** 2026-06-22
**Source change:** `openspec/changes/archive/2026-06-22-add-opsx-loop-harness/`

## Context

An autonomous loop edits the working tree without a human approving every move.
The opsx-superpowers `Worktree Mode` previously defaulted to `same-tree`. We had
to decide the default isolation posture for the loop.

## Decision Drivers

- An autonomous loop needs blast-radius containment (harness-engineering guidance
  is explicit: isolate with a worktree / devcontainer / VM).
- Consistency vs ceremony for trivial (XS) changes.
- The loop's verdict-freshness + file-contract diffs need a stable, isolated base.

## Considered Options

### Option A: worktree-required default for ALL Scales
Every change runs in `opsx/<change>` worktree; `same-tree` is an explicit override.

**Pros:** isolation is a safety prerequisite for autonomy, not a nicety; consistent.
**Cons:** ceremony for typo-level fixes (mitigated: `same-tree` is one keystroke away).

### Option B: worktree-required at M+ only, eligible at XS/S
The adversarial reviewers' suggested compromise.

**Pros:** less ceremony for trivial fixes.
**Cons:** the autonomous loop's safety floor would vary by Scale.

### Option C: keep same-tree default
**Cons:** an autonomous loop mutating the live tree with no isolation — unsafe.

## Decision Outcome

**Chosen option:** A (explicit owner decision, retained over the reviewers' Option B).

**Rationale:** the owner chose "default for all sizes." Isolation is the safety
floor for autonomy; the `same-tree` override keeps trivial fixes cheap.

## Consequences

**Positive:** every autonomous run is sandboxed; clean rollback on failure.
**Negative:** XS overhead (worktree create/merge/cleanup) unless overridden.
**Neutral:** apply owns the worktree lifecycle; `Diff Base SHA` (merge-base) is immutable per branch.

## Links

- `openspec/changes/archive/2026-06-22-add-opsx-loop-harness/design.md` (Decision D4)
- Related: ADR-0005, ADR-0007
