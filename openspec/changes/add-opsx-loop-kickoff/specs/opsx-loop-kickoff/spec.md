# Capability: opsx-loop-kickoff

## ADDED Requirements

### Requirement: Single-command guaranteed loop

THE opsx-loop pi extension SHALL register an `/opsx-loop <change>` command that starts a guaranteed loop: it injects an initial worker turn directed at the openspec-loop skill for the change, and after each subsequent agent turn evaluates `opsx-gate` and either continues or stops.

#### Scenario: Starting the loop injects a worker turn
- **WHEN** the user issues `/opsx-loop add-clipboard-extension`
- **THEN** the extension SHALL record the change as the active loop with its turn count reset to zero and SHALL inject one worker turn directed at advancing that change toward a green opsx-gate

#### Scenario: Replacing an active loop
- **WHILE** a loop is already active
- **WHEN** the user issues `/opsx-loop` with a new change
- **THEN** the new change SHALL replace the active loop and the turn count SHALL reset to zero

### Requirement: opsx-gate is the deterministic judge

WHILE a loop is active, WHEN a worker turn completes, THE extension SHALL run `opsx-gate <change>` (passing `--worktree <path>` when one is resolved) and treat exit 0 as met and any non-zero exit as not met, using the gate's report as the directive for the next turn. The extension SHALL NOT decide completion from agent self-assessment.

#### Scenario: Green gate stops the loop
- **WHILE** a loop is active
- **WHEN** a worker turn completes and `opsx-gate` exits 0
- **THEN** the extension SHALL clear the active loop, stop injecting turns, and notify the user the change is ready to archive

#### Scenario: Red gate continues the loop
- **WHILE** a loop is active and the turn budget is not exhausted
- **WHEN** a worker turn completes and `opsx-gate` exits non-zero
- **THEN** the extension SHALL inject another worker turn carrying the gate's failed-check report as guidance

#### Scenario: Judge command failure is non-fatal
- **WHILE** a loop is active
- **IF** the `opsx-gate` command cannot be executed at all
- **THEN** the extension SHALL treat the result as not met, surface an explanatory reason, and continue without crashing the session

### Requirement: Budget from review front-matter

THE extension SHALL bound the loop with a maximum number of continuation turns read from `loop_max_iterations` in the change's `review.md` front-matter, falling back to a built-in default when absent or unparseable.

#### Scenario: Budget exhausted stops and preserves
- **WHILE** a loop is active and the gate is still red
- **IF** the elapsed turn count reaches the budget
- **THEN** the extension SHALL stop injecting turns, clear the active loop, inform the user the budget was exhausted, and NOT remove any worktree

#### Scenario: Default budget when front-matter absent
- **IF** the change's review.md has no parseable `loop_max_iterations`
- **THEN** the extension SHALL apply a built-in default budget without error

### Requirement: Status and clear subcommands

WHEN the user issues `/opsx-loop` with the `status` keyword (or no argument) or with the `clear` directive (or an accepted alias), THE extension SHALL report the active loop's change/turns/budget, or clear the active loop and stop continuing turns, respectively, and SHALL offer `status` and `clear` as argument completions.

#### Scenario: Status reports the active loop
- **WHILE** a loop is active
- **WHEN** the user issues `/opsx-loop status` (or `/opsx-loop` with no change)
- **THEN** the report SHALL show the active change, elapsed turns, the budget, and the last gate reason

#### Scenario: Clear stops the loop
- **WHILE** a loop is active
- **WHEN** the user issues `/opsx-loop clear` (or an alias: stop, off, reset, none, cancel)
- **THEN** the active loop SHALL be removed and no further turns SHALL be injected

### Requirement: Interrupt or error stops the loop

IF a worker turn ends because the user interrupted it or because the turn errored, THEN THE extension SHALL stop the loop and clear the active loop instead of injecting another turn.

#### Scenario: User interrupt halts the loop
- **WHILE** a loop is active
- **IF** the user interrupts the current worker turn
- **THEN** the extension SHALL clear the loop and not inject another turn, informing the user the loop was stopped

#### Scenario: Goal extension is not modified
- **WHEN** the opsx-loop extension is deployed
- **THEN** the `goal` extension's files SHALL be unchanged, and both extensions SHALL operate independently

---

## Acceptance criterion quality checklist

| AC ID | Testable | Solution-free | Unambiguous | Consistent | Complete |
|---|---|---|---|---|---|
| opsx-loop-kickoff.single-command-guaranteed-loop | [x] | [x] | [x] | [x] | [x] |
| opsx-loop-kickoff.opsx-gate-is-the-deterministic-judge | [x] | [x] | [x] | [x] | [x] |
| opsx-loop-kickoff.budget-from-review-front-matter | [x] | [x] | [x] | [x] | [x] |
| opsx-loop-kickoff.status-and-clear-subcommands | [x] | [x] | [x] | [x] | [x] |
| opsx-loop-kickoff.interrupt-or-error-stops-the-loop | [x] | [x] | [x] | [x] | [x] |
