<!-- authored: delegate spec-consolidation -->
# Capability: goal-loop

Delta for simplify-and-parallelize-opsx-workflow (B4): record goal-loop's
deprecation/fallback status relative to the primary opsx-loop host. No functional change;
removal is explicitly out of scope for this change.

## ADDED Requirements

### Requirement: Deprecation and Fallback Status

THE goal-loop capability SHALL be documented as the GENERIC FALLBACK loop driver, WHILE the opsx-loop extension is the PRIMARY loop host for opsx-superpowers changes; goal-loop SHALL retain its current behavior unchanged (no functional change), and its removal SHALL be out of scope for this change — the status note SHALL NOT alter any existing goal-loop requirement or scenario.

#### Scenario: Status documented without behavior change
- **WHEN** the goal-loop capability documentation is read
- **THEN** it SHALL state that goal-loop is the generic fallback driver and opsx-loop is the primary loop host, AND every existing goal-loop behavior SHALL remain unchanged

#### Scenario: Removal is out of scope
- **WHILE** this change records the deprecation/fallback status
- **THEN** goal-loop SHALL NOT be removed and no existing requirement or scenario SHALL be deleted or weakened by this change
