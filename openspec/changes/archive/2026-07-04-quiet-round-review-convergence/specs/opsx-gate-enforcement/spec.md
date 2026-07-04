# opsx-gate-enforcement (delta)

## ADDED Requirements

### Requirement: Migration Sweep Gate Check

WHERE a change directory contains a `sweep.txt` declaration, THE `opsx gate` SHALL run the migration-completeness sweep as one of its cheap deterministic checks, grepping the SAME resolved artifact root the gate resolves for its other checks (the validated worktree when the change is worktree-required, the integration checkout otherwise), and SHALL emit a `GATE-FAIL sweep` line when the sweep reports hits, and WHERE no declaration exists the gate SHALL NOT run or require the sweep, so undeclared changes are unaffected.

#### Scenario: Declared sweep enforced by the gate
- **WHEN** a change with a sweep.txt has a declared pattern matching a shipped surface
- **THEN** opsx gate SHALL fail with a GATE-FAIL sweep line naming the check

#### Scenario: Clean declared sweep passes the gate check
- **WHEN** a change with a sweep.txt has no pattern hits
- **THEN** the sweep check SHALL pass and not appear as a GATE-FAIL

#### Scenario: Undeclared changes unaffected
- **IF** a change has no sweep.txt
- **THEN** the gate SHALL run no sweep check for it and its exit code SHALL be unaffected

#### Scenario: Sweep reads the resolved worktree
- **WHILE** the change is worktree-required and the sweep-relevant fixes exist only on the worktree branch
- **WHEN** opsx gate runs with the worktree resolved
- **THEN** the sweep check SHALL grep the worktree's tracked files and pass, never false-failing against the integration root's stale copies
