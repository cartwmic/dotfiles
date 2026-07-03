# ADR-0018: Persistent reviewer splits resolve via one late disclosure round

**Status:** Accepted
**Date:** 2026-07-03
**Source change:** `openspec/changes/add-opsx-review-convergence/`

## Context

Multi-model blind gating reviews can split (one pass, one fail) indefinitely
under an implicit unanimous-pass rule; round count scales with reviewer count ×
taste variance. Blindness is the discipline's core value and its breaks must be
bounded and marked.

## Decision Drivers

- Preserve blindness as the default; any break must be late, bounded, explicit
- Force reviewers to reconcile before interrupting the human
- Constitution IX multi-model requirement must remain satisfiable

## Considered Options

### Option A: One non-blind disclosure-consensus round (trigger: split 2 consecutive rounds, or a stop firing with a split; max 1/change)
### Option B: Unanimous pass, unbounded rounds (status quo)
### Option C: Convergent-findings (quorum) gating — findings gate only if ≥2 reviewers cite them
### Option D: Arbiter model on disputed findings

## Decision Outcome

**Option A.** Sealed as `review_mode: disclosure-consensus`; satisfies a
gating-required multi-model review only when ≥2 distinct models participated;
`degraded-single-model` never does. B is the observed treadmill; C silently
weakens the gate every round (singleton P1 from the stronger model never
blocks); D adds a third opinion without forcing the original reviewers to
reconcile.

## Consequences

- Disagreement remains signal: blind rounds never leak the ledger or other
  reviewers' output; exactly one sanctioned disclosure.
- First applied on its own source change: rounds 1-2 split, disclosure round
  converged to pass.
