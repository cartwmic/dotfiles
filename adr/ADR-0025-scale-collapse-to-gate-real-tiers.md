# ADR-0025: Scale collapses to the three gate-real tiers plus an explicit full_rigor flag

**Status:** accepted (2026-07-03, simplify-and-parallelize-opsx-workflow)

## Context

The schema advertised five Scale tiers (XS/S/M/L/XL) but the deterministic
gate distinguished only three behaviors — M, L, and XL shared one
required-artifact set, and the L/XL extras (ADR promotion,
adversarial-on-analyze, retrospective) were skill-managed side effects of a
label. Five labels for three gate-observable behaviors was cognitive load
with no enforcement behind it (simplicity audit, verdict: mixed).

## Decision

- Scale vocabulary is `XS | S | M`. Former L/XL map to `M + full_rigor: true`.
- `full_rigor` is an explicit boolean front-matter flag that opts a Scale-M
  change into the extras: standalone blind clarify + analyze, required
  design.md, independent doneness judge, ADR promotion,
  adversarial-on-analyze, retrospective, and the former L loop budget.
- The gate fails CLOSED on `L`/`XL` (relabel remedy named) and on a
  non-boolean `full_rigor`. Absent `worktree_mode` derives XS/S ⇒ same-tree,
  M ⇒ worktree-required; absent `code_review_mode` derives gating-required at
  M, advisory below (fail-open-by-omission eliminated).
- Archived changes and historical review records are never rewritten.

## Consequences

- What you declare is what the gate enforces; rigor is opt-in and visible in
  front-matter rather than implied by a label.
- In-flight L/XL changes must relabel to `M + full_rigor: true` after deploy.
- The gate deployed with this change judges future changes; this change
  itself was gated under the prior 5-tier gate for its whole lifecycle.
