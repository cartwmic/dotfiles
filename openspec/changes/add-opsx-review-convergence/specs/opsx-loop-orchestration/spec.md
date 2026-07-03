<!-- authored: in-session -->
# Capability: opsx-loop-orchestration

## ADDED Requirements

### Requirement: Review Dispatch Bound By Convergence Discipline

THE openspec-loop orchestration SHALL conduct gating review rounds under the opsx-review-convergence discipline: full-diff blind re-review each round, an orchestrator-maintained round ledger, the trajectory/budget stop conditions, at most one disclosure round on persistent split, and the decision-audit landing when open P0/P1 findings survive the stops.

#### Scenario: Re-dispatch consults the stop conditions first
- **WHEN** a gating review round returns a fail verdict and fixes have been committed
- **THEN** the orchestration SHALL evaluate the convergence stop conditions (converged, treadmill trajectory, round budget) before dispatching the next blind round, and SHALL NOT dispatch when a stop condition holds

#### Scenario: Non-convergence lands, never spins
- **IF** stop conditions fire with open P0/P1 findings (after any disclosure round)
- **THEN** the orchestration SHALL present the decision-audit landing to the user instead of continuing review cycles or escalating to additional reviewer models

### Requirement: Pre Apply Surface Audit Dispatch

WHERE the frozen intent is property-style (a codebase-wide property claim rather than an enumerable diff), THE orchestration SHALL dispatch the advisory surface audit before the first implementation task, and SHALL feed its enumeration into tasks.md and the intent's stated-scope prose before gating reviews begin.

#### Scenario: Audit precedes implementation
- **WHEN** apply begins for a property-style intent without a completed surface audit
- **THEN** the orchestration SHALL dispatch the advisory audit before executing implementation tasks

#### Scenario: Enumerable-diff intents skip the audit
- **WHERE** the intent enumerates its scope concretely
- **THEN** no surface audit dispatch is required

### Requirement: Scope Widening Handled In The Loop

WHILE the loop is advancing a change, WHEN a gating reviewer or the doneness judge reports a finding outside the intent's stated scope, THE orchestration SHALL apply the opsx-review-convergence scope-widening protocol — widen with a logged evidence entry when the finding is required to meet the frozen intent, route to follow-ups.md otherwise — rather than silently fixing, silently dropping, or halting on every out-of-scope finding.

#### Scenario: Widening logged before fixing
- **WHEN** the orchestration decides an out-of-scope finding is required to meet the frozen intent
- **THEN** it SHALL record the Scope Expansions entry (what + evidence) in review.md before committing the fix

#### Scenario: Deferral is visible
- **WHEN** the orchestration routes an out-of-scope finding to follow-ups.md
- **THEN** the routing SHALL be recorded with the finding's severity and origin so the archive step can surface it

---

## Acceptance criterion quality checklist

| AC ID | Testable | Solution-free | Unambiguous | Consistent | Complete |
|---|---|---|---|---|---|
| opsx-loop-orchestration.review-dispatch-bound-by-convergence-discipline | [x] | [x] | [x] | [x] | [x] |
| opsx-loop-orchestration.pre-apply-surface-audit-dispatch | [x] | [x] | [x] | [x] | [x] |
| opsx-loop-orchestration.scope-widening-handled-in-the-loop | [x] | [x] | [x] | [x] | [x] |
