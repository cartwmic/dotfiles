# ADR-0034: Dual-tree read-only dispatch window with narrow bookkeeping exclusion and concurrency carve-outs

## Status

Accepted (2026-07-06, change `add-opsx-design-fidelity-gate`)

## Context

Session 019f2d9f: a reviewer wrote the INTEGRATION checkout's progress.md —
invisible to the single-tree window covering only the reviewed worktree. And
the original whole-change-dir exclusion would have blinded the window to a
fidelity judge rewriting the very design.md it was judging.

## Decision Drivers

- Cover every tree a dispatched reviewer can plausibly write.
- Parallel loops must not false-void on each other's legitimate activity.
- Judged inputs must never be writable-in-window without voiding.

## Considered Options

- Reviewed-tree-only window — rejected: misses integration-checkout writes.
- Snapshot every worktree — rejected: unrelated concurrent changes mutate
  legitimately; voiding on them deadlocks parallel development.
- Whole-change-dir exclusion — rejected (analyze R5): the fidelity judge's
  subject matter lives in the change dir.

## Decision Outcome

Pre/post round snapshots (`git rev-parse HEAD` + `git status --porcelain=v1`)
cover the reviewed worktree AND the integration checkout. Exclusion is ONLY
the dispatched change's bookkeeping files (review.md, follow-ups.md); judged
inputs always void. Carve-outs, deterministic by path prefix: intervening
integration commits touching only OTHER changes' change dirs or the
dispatched change's own bookkeeping never void; sibling uncommitted
authoring inside its own change dir never voids. Everything else voids ALL
round verdicts. Surgical restore is scoped symmetrically — sibling change
dirs are never restored or deleted; only window-introduced deltas; never a
blanket `git clean`.

## Consequences

- Judge tampering with judged inputs voids the round before digests seal
  over it.
- N concurrent loops share the pre-worktree tree without manufactured
  INVALID rounds; a sibling archive-merge mid-window still voids (rare,
  fail-closed, accepted residual).
