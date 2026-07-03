# ADR-0023: Worktree locator is published to the integration checkout; convention fallback is single-sourced

**Status:** Accepted
**Date:** 2026-07-03
**Source change:** `openspec/changes/harden-opsx-loop-latch-and-stop/`

## Context

Apply recorded `Worktree Path` on the change branch only, while `opsx gate` and the
loop extension resolve review.md from the integration checkout — gate-from-main and
gate-from-worktree disagreed about the same change (red-loop observed 2026-07-03,
hot-patched per-change). Any fallback derivation duplicated across consumers would
reintroduce the same divergence class.

## Decision

Primary: the apply workflow commits the locator fields (`Worktree Path`,
`Diff Base SHA`, `Integration Branch`) to the INTEGRATION branch at worktree-creation
time; the resulting non-fast-forward archive merge is the accepted cost. Backstop:
gate and extension fall back to the canonical convention path when the recorded
locator is absent/invalid — derived EXACTLY ONCE (`opsx_wt_convention_path`,
normalized to the repo's MAIN worktree root so the derivation is identical from any
checkout) and exposed read-only as `opsx worktree path <change>`; the extension
shells it, never re-derives. `--path`-override worktrees are out of the fallback's
reach BY DESIGN — publication covers them. Explicit `--worktree` arguments are
operator assertions: validated immediately and loudly in every worktree_mode.

## Consequences

- Gate-view equality (integration ↔ worktree) becomes an invariant with a pinned
  test; the round-2 review P0 (derivation from current checkout root) is the
  cautionary case.
- Rejected: publication-only (pre-rule changes keep split-braining) and
  fallback-only (locator field becomes decorative).
- Non-ff merges accepted repo-wide for opsx changes.
