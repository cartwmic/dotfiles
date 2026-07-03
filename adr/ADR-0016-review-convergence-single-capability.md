# ADR-0016: Review-convergence discipline lives in one capability with thin bindings

**Status:** Accepted
**Date:** 2026-07-03
**Source change:** `openspec/changes/add-opsx-review-convergence/`

## Context

The gating-review convergence rules (verdict contract, severity floor, round
ledger, stop conditions, disclosure round, landing, scope widening, model
stability) span the loop orchestration, post-impl review, and workflow-schema
capabilities. Cross-capability invariants like "a stop never forges green"
must not drift apart across spec files.

## Decision Drivers

- Single source of truth for discipline invariants
- Archive robustness (MODIFIED-header matching is fragile; observed 2026-07-02)
- Small review surface per future edit

## Considered Options

### Option A: New `opsx-review-convergence` capability; modified capabilities get thin additive ADDED bindings
### Option B: Spread the rules across the three existing capabilities
### Option C: MODIFIED requirements rewriting existing blocks in place

## Decision Outcome

**Option A.** All convergence rules specified once; `opsx-loop-orchestration`,
`opsx-post-impl-review`, and `opsx-workflow-schema` bind to the discipline with
thin additive requirements. The only MODIFIED block is the blind-conduct
exception that a spread approach would have needed anyway.

## Consequences

- Future discipline edits touch one spec; bindings rarely change.
- Constrains future spec layout: convergence semantics must not be restated in
  consumer capabilities (drift risk if violated — see analyze finding F8).
