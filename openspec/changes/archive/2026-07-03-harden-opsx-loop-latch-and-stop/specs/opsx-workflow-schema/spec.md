<!-- authored: in-session -->
# Capability: opsx-workflow-schema

## ADDED Requirements

### Requirement: Loop hold front-matter keys

THE review.md template SHALL document optional `loop_hold` and `loop_hold_reason`
front-matter keys: `loop_hold: true` is an orchestrator-settable landing signal read by
the loop host (NOT by opsx gate — the gate SHALL remain ignorant of hold state), and a
`true` value REQUIRES a non-empty `loop_hold_reason`. The template SHALL state the
clearing rule: only an explicit named re-arm clears a hold; agents never clear it.

#### Scenario: Template documents the hold contract
- **WHEN** review.md is authored from the template
- **THEN** the template SHALL carry commented `loop_hold` / `loop_hold_reason` keys explaining the set-by-orchestrator, cleared-by-named-re-arm-only contract and that the gate does not read them

#### Scenario: Gate ignores hold state
- **WHEN** opsx gate evaluates a change whose review.md carries `loop_hold: true`
- **THEN** gate checks and exit code SHALL be unaffected by the hold fields
