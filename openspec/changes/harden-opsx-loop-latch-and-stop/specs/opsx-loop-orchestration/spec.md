<!-- authored: in-session -->
# Capability: opsx-loop-orchestration

## ADDED Requirements

### Requirement: Terminal landings set the loop hold

THE orchestrator SHALL, WHEN declaring a landing state that must not be re-driven by
loop continuation — a decision-audit landing after review non-convergence, a terminal
green-gate report already presented, or any stop that awaits a human ruling — set
`loop_hold: true` with a non-empty `loop_hold_reason` in the change's review.md
front-matter (committed as part of the landing turn) instead of relying on prose
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
