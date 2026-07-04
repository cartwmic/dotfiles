# ADR-0024: Parallel opsx loops are coordinated by visibility, not locks

**Status:** accepted (2026-07-03, simplify-and-parallelize-opsx-workflow)

## Context

The workflow must support 2–3 concurrent loops (different changes, separate pi
sessions, worktrees) for a solo developer. The pre-audit plan proposed
per-change flocks with PID stale-lock healing, a distill session nonce, and
branch-first authoring with a separate control file. An independent simplicity
audit found those guarded windows a human already gates (arming is an explicit
human-only action per ADR-0021/0022; distill cross-adopt is caught at the
ADR-0014 confirm pause) while the actual gap — no cross-session view of the
fleet — went unaddressed. Propose phases are path-disjoint by construction
(each writes only `openspec/changes/<change>/`), so the only real
propose-overlap mechanism is the shared git index.

## Decision

Coordinate concurrent loops with deterministic checks and a read-only fleet
view instead of mutual exclusion:

- `opsx status`: per-change Scale, cheap-gate summary, worktree health,
  `loop_hold`, and Diff-Base-behind-main staleness. See collisions early.
- `opsx archive-check`: land-base-currency (merge-base(branch, main) == main
  HEAD; same-tree exempt), duplicate-ADR scan, and an advisory multi-dir
  commit detector (merge-aware, first-parent net effect).
- Path-scoped integration commits (`git commit -m "<msg>" -- <paths>`) close
  the index-sweep class.

Flock/nonce are rejected; branch-first + `.opsx-control` are deferred until a
real merge-collision is observed (revisit trigger, not dogma).

## Consequences

- No lock-liveness machinery to maintain or heal; collisions become visible
  instead of impossible.
- The second lander pays a rebase + fresh review (staleness fires) — accepted.
- review.md merge conflicts at land remain possible and stay a manual,
  seconds-long resolution.
