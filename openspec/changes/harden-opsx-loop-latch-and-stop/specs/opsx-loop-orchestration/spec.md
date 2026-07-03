<!-- authored: in-session -->
# Capability: opsx-loop-orchestration

## ADDED Requirements

### Requirement: Terminal landings set the loop hold

THE orchestrator SHALL, WHEN declaring a landing state that must not be re-driven by
loop continuation — a decision-audit landing after review non-convergence, a terminal
green-gate report already presented, or any stop that awaits a human ruling — set
`loop_hold: true` with a non-empty `loop_hold_reason` in the change's review.md
front-matter — the same copy the loop host resolves from the integration checkout, so
the hold is observable to the host — committed as part of the landing turn, instead of
relying on prose
announcements or stall-guard exhaustion, so the host loop observes the landing
deterministically. The orchestrator SHALL NEVER clear a `loop_hold` itself — clearing is
reserved to the human named re-arm.

#### Scenario: Decision-audit landing holds the loop
- **WHEN** the orchestrator presents a decision audit after review stop conditions fire
- **THEN** it SHALL set `loop_hold: true` with a reason pointing at the audit before ending the turn, and the loop SHALL NOT re-inject a continuation

#### Scenario: Orchestrator never clears its own hold
- **WHILE** review.md carries `loop_hold: true`
- **WHEN** the orchestrator concludes further work is warranted
- **THEN** it SHALL surface that recommendation to the user and SHALL NOT remove the hold fields itself

#### Scenario: Hold is written to the copy the loop host reads
- **WHILE** the change's verdict artifacts (verify.md, code-review.md, doneness.md) live in the apply worktree
- **WHEN** the orchestrator sets a landing hold
- **THEN** it SHALL write and commit the `loop_hold` fields in the review.md resolved from the INTEGRATION checkout (the copy the loop host and gate read), not solely the worktree copy, so the hold cannot be split-brained into invisibility

## MODIFIED Requirements

### Requirement: Review Dispatch Bound By Convergence Discipline

THE openspec-loop orchestration SHALL conduct gating review rounds under the opsx-review-convergence discipline: full-diff blind re-review each round, an orchestrator-maintained round ledger, the trajectory/budget stop conditions, at most one disclosure round on persistent split, and the decision-audit landing when open P0/P1 findings survive the stops.

#### Scenario: Re-dispatch consults the stop conditions first
- **WHEN** a gating review round returns a fail verdict and fixes have been committed
- **THEN** the orchestration SHALL evaluate the convergence stop conditions (converged, treadmill trajectory, round budget) before dispatching the next blind round, and SHALL NOT dispatch when a stop condition holds

#### Scenario: Non-convergence lands, never spins
- **IF** stop conditions fire with open P0/P1 findings (after any disclosure round)
- **THEN** the orchestration SHALL present the decision-audit landing to the user instead of continuing review cycles or escalating to additional reviewer models

#### Scenario: Landing halts loop continuation
- **WHEN** the decision-audit landing is presented
- **THEN** the orchestration SHALL stop the drive-to-green loop's continuation by setting `loop_hold: true` with a reason pointing at the audit (per the terminal-landing requirement); WHERE the loop host does not support `loop_hold`, performing no further change-directory or commit activity (so the host's stall detection stops the loop) remains the fallback — in both cases presenting the audit exactly once rather than re-presenting it on every re-injected turn
