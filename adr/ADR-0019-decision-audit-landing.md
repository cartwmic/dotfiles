# ADR-0019: Non-converging reviews land in a tiered decision audit, never forced green

**Status:** Accepted
**Date:** 2026-07-03
**Source change:** `openspec/changes/add-opsx-review-convergence/`

## Context

When stop conditions fire with open P0/P1, the loop needs a defined terminal
state. Observed failure mode: the orchestrator, unable to justify stopping,
escalated to ad-hoc extra reviewer models (5-model "convergence blitz"). The
user's standing principle: automation stops before archive/deploy; the human
retains control at judgment boundaries.

## Decision Drivers

- Non-convergence is information, not failure to hide
- No deadlock: a waiver must produce a consumable sealed verdict
- No model shopping as a deadlock-breaker

## Considered Options

### Option A: Tiered decision-audit landing (🔴/🟡/🟢) with fix/waive/re-scope rulings
### Option B: Plain budget-exhausted fail-report
### Option C: Auto-waive advisory residue

## Decision Outcome

**Option A.** The landing presents open findings, autonomous decisions, and all
scope expansions once, then halts loop continuation. Rulings: **fix** grants a
recorded round-budget extension (resumed rounds are dispatchable); **waive**
records the finding user-waived in follow-ups.md and re-seals `Verdict: pass`
with `waived_by_user` (reviewed range unchanged — pass by explicit human
authorization, never self-authored); **re-scope** returns to explore. B dumps
synthesis on the user with no waiver semantics (re-run deadlock); C is
subsumed by the severity floor for P2/P3 and would forge green for P0/P1.

## Consequences

- Dispatching reviewer models beyond the resolved `review` set is prohibited.
- The landing must be presented exactly once per stop (host loop-stop, else
  stall detection ends re-injection).
