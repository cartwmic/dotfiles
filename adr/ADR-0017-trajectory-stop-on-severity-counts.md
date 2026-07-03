# ADR-0017: Review treadmill detection uses severity counts, not finding identity

**Status:** Accepted
**Date:** 2026-07-03
**Source change:** `openspec/changes/add-opsx-review-convergence/`

## Context

Blind review rounds produce free-text findings from fresh contexts — the same
defect is phrased differently every round, so cross-round finding matching is
unreliable. The loop needs a deterministic treadmill signal (evidence: session
019f1ed4, 2026-07-02 — 6-8 unbounded gating rounds plus a 5-model blitz).

## Decision Drivers

- Determinism (no model call in the stop decision)
- Comparability across rounds (fixed reviewer set + embedded rubric)
- ARC (adversarial-review-cycle) precedent: P0+P1 trajectory stop is proven

## Considered Options

### Option A: Trajectory stop on consolidated P0+P1 counts (flat/rising across the two most recent rounds), consolidation = MAX across reviewers per severity
### Option B: Doneness-style gap-set ratchet on normalized findings
### Option C: Semantic dedup via an extra model call

## Decision Outcome

**Option A.** Counts are cheap, deterministic, and comparable; both
non-convergence and oscillation surface as flat counts. B never trips on
blind free-text (normalization fails); C puts a model in the stop path.
Backstopped by `review_max_rounds` (default 5, front-matter override,
user-extendable at the landing).

## Consequences

- Ledger counts must be sealed per round in the review artifact (mechanization-
  ready fields).
- Severity-rubric calibration in every dispatch prompt is a hard dependency —
  uncalibrated severities make the trajectory noise.
