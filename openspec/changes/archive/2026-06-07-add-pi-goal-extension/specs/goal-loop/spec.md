# Capability: goal-loop

<!--
Domain note: openspec/domain.md invariants are chezmoi-environment facts
(deployment paths, launchd PATH, etc.); none constrain goal-loop's RUNTIME
behavior beyond the deployment path already captured in proposal.md
(invariant #4: dot_pi/ → ~/.pi/, distinct from non-deployed root .pi/).
A goal is scoped to a single pi session per the pi session model.
EARS error/unwanted conditions use IF…THEN; nominal triggers use WHEN.
-->

## ADDED Requirements

### Requirement: Set a Goal

WHEN the user issues the goal command with a non-empty completion condition, THE goal-loop SHALL store that condition as the session's active goal, reset its turn count to zero, and start one worker turn directed by the condition without requiring a separate prompt.

#### Scenario: Setting a goal starts work
- **WHEN** the user issues the goal command with the condition "all tests in test/auth pass"
- **THEN** the condition becomes the session's active goal with a turn count of zero
- **AND** a worker turn begins directed by that condition

#### Scenario: Setting a goal replaces an active one
- **WHILE** a goal is already active
- **WHEN** the user issues the goal command with a new condition
- **THEN** the new condition replaces the active goal and the turn count resets to zero

### Requirement: Check Goal Status

WHEN the user issues the goal command with no condition or with the explicit status keyword, THE goal-loop SHALL report whether a goal is active and, if so, its condition, elapsed turn count, configured turn budget, and the most recent evaluation reason. THE goal-loop SHALL offer the status and clear directives as argument completions so they are discoverable.

#### Scenario: Status with an active goal
- **WHILE** a goal is active
- **WHEN** the user issues the goal command with no condition
- **THEN** the report shows the active condition, the elapsed turn count, the turn budget, and the most recent evaluation reason

#### Scenario: Explicit status keyword is not treated as a condition
- **WHEN** the user issues the goal command with the argument `status` (or `?`)
- **THEN** the status is reported and no goal is set to that word

#### Scenario: Subcommands are discoverable via completion
- **WHEN** the user begins typing an argument to the goal command
- **THEN** `status` and `clear` are offered as argument completions

#### Scenario: Status with no active goal
- **WHILE** no goal is active
- **WHEN** the user issues the goal command with no condition
- **THEN** the report states that no goal is active

### Requirement: Clear a Goal

WHEN the user issues the goal command with the clear directive or any accepted alias (stop, off, reset, none, cancel), THE goal-loop SHALL remove the active goal and stop continuing turns.

#### Scenario: Clear an active goal
- **WHILE** a goal is active
- **WHEN** the user issues the goal command with the clear directive
- **THEN** the active goal is removed and no further turns are injected

#### Scenario: Clear alias is accepted
- **WHEN** the user issues the goal command with any of: stop, off, reset, none, cancel
- **THEN** the active goal is cleared identically to the clear directive

### Requirement: Judge Each Completed Turn

WHILE a goal is active, WHEN a worker turn completes, THE goal-loop SHALL evaluate the active condition against the conversation transcript using a separate evaluator that is distinct from the worker, considering only content already surfaced in the transcript, and obtain a met-or-not result with a short reason.

#### Scenario: Evaluation runs after a worker turn
- **WHILE** a goal is active
- **WHEN** a worker turn completes
- **THEN** the active condition and the conversation transcript are evaluated by a separate evaluator
- **AND** a result is produced containing a met flag and a reason

### Requirement: Continue When Condition Not Met

WHILE a goal is active, WHEN evaluation reports the condition is not met and the turn budget is not exhausted, THE goal-loop SHALL start another worker turn carrying the evaluation reason as its directive.

#### Scenario: Not-met result drives another turn
- **WHILE** a goal is active and the turn count is below the turn budget
- **WHEN** evaluation reports the condition is not met
- **THEN** another worker turn begins carrying the evaluation reason as guidance

### Requirement: Complete When Condition Met

WHILE a goal is active, WHEN evaluation reports the condition is met, THE goal-loop SHALL clear the active goal, stop continuing turns, and notify the user that the goal was achieved with the evaluation reason.

#### Scenario: Met result ends the loop
- **WHILE** a goal is active
- **WHEN** evaluation reports the condition is met
- **THEN** the active goal is cleared, no further turns are injected, and the user is notified the goal was achieved with the reason

### Requirement: Bound the Loop With a Turn Budget

THE goal-loop SHALL enforce a configurable maximum number of continuation turns per goal, defaulting to 25.

#### Scenario: Budget exhausted stops the loop
- **WHILE** a goal is active and the condition is still not met
- **IF** the elapsed turn count reaches the configured turn budget
- **THEN** the goal-loop stops injecting further turns, clears the active goal, and informs the user the budget was exhausted

### Requirement: Handle Evaluation Failure

IF the evaluator cannot be resolved, authenticated, or produces an unparseable result, THEN THE goal-loop SHALL treat the condition as not yet met, surface an explanatory reason, and continue without terminating the session abnormally.

#### Scenario: Evaluator unavailable is non-fatal
- **WHILE** a goal is active
- **IF** no evaluator can be resolved or authenticated
- **THEN** the condition is treated as not yet met, an explanatory reason is surfaced, and the session does not crash

#### Scenario: Unparseable verdict defaults to not-met
- **WHILE** a goal is active
- **IF** the evaluator returns a result that cannot be parsed into a met flag
- **THEN** the condition is treated as not met with the raw output surfaced as the reason

### Requirement: Evaluate Each Turn Once

WHILE a goal is active, THE goal-loop SHALL evaluate exactly one time per completed worker turn, ensuring an injected continuation turn does not trigger overlapping or duplicate evaluation of the prior turn.

#### Scenario: One evaluation per turn
- **WHILE** a goal is active
- **WHEN** the goal-loop injects a continuation turn after a not-met result
- **THEN** that continuation turn is evaluated exactly once on completion, with no overlapping or duplicate evaluation of the prior turn

### Requirement: Interrupt Stops the Loop

IF a worker turn ends because the user interrupted it or because the turn errored, THEN THE goal-loop SHALL stop the loop and clear the active goal instead of starting another turn. THE clear directive SHALL additionally stop any in-flight worker turn.

#### Scenario: User interrupt halts the loop
- **WHILE** a goal is active
- **IF** the user interrupts the current worker turn
- **THEN** the goal-loop clears the goal and does not start another turn, and the user is informed the goal was stopped

#### Scenario: Turn error halts the loop
- **WHILE** a goal is active
- **IF** a worker turn ends in error
- **THEN** the goal-loop clears the goal and does not start another turn

#### Scenario: Clear stops in-flight work
- **WHILE** a goal is active and a worker turn is in progress
- **WHEN** the user issues the clear directive
- **THEN** the active goal is removed and the in-progress worker turn is stopped

### Requirement: Configurable Judge and Budget

WHERE a configuration file co-located with the extension is present, THE goal-loop SHALL read the judge model and the turn budget from it. An environment variable SHALL override the file value, and a built-in default SHALL apply when neither the environment variable nor the file supplies a valid value. Invalid or missing configuration values SHALL be ignored without error.

#### Scenario: Config file supplies the judge model and budget
- **WHERE** the config file sets a judge model and a turn budget
- **WHEN** a goal is set
- **THEN** the configured judge model is used for evaluation and the configured value is used as the turn budget

#### Scenario: Environment variable overrides the config file
- **WHERE** both the config file and the corresponding environment variable set a value
- **WHEN** a goal is set
- **THEN** the environment variable's value takes precedence over the config file

#### Scenario: Invalid configuration falls back
- **IF** a configuration value is missing or invalid
- **THEN** the next source in precedence (environment variable, then built-in default) applies, with no error

### Requirement: Show Active-Goal Indicator

WHILE a goal is active, THE goal-loop SHALL display a status indicator showing that a goal is running and how many turns have elapsed, and SHALL remove the indicator when the goal is cleared, achieved, or its budget is exhausted.

#### Scenario: Indicator visible while active
- **WHILE** a goal is active
- **THEN** a status indicator shows the active goal and the elapsed turn count

#### Scenario: Indicator removed when inactive
- **WHEN** the goal is cleared, achieved, or its budget is exhausted
- **THEN** the status indicator is removed

---

## Acceptance criterion quality checklist

| AC ID | Testable | Solution-free | Unambiguous | Consistent | Complete |
|---|---|---|---|---|---|
| goal-loop.set-a-goal | [x] | [x] | [x] | [x] | [x] |
| goal-loop.check-goal-status | [x] | [x] | [x] | [x] | [x] |
| goal-loop.clear-a-goal | [x] | [x] | [x] | [x] | [x] |
| goal-loop.judge-each-completed-turn | [x] | [x] | [x] | [x] | [x] |
| goal-loop.continue-when-condition-not-met | [x] | [x] | [x] | [x] | [x] |
| goal-loop.complete-when-condition-met | [x] | [x] | [x] | [x] | [x] |
| goal-loop.bound-the-loop-with-a-turn-budget | [x] | [x] | [x] | [x] | [x] |
| goal-loop.handle-evaluation-failure | [x] | [x] | [x] | [x] | [x] |
| goal-loop.evaluate-each-turn-once | [x] | [x] | [x] | [x] | [x] |
| goal-loop.show-active-goal-indicator | [x] | [x] | [x] | [x] | [x] |
| goal-loop.configurable-judge-and-budget | [x] | [x] | [x] | [x] | [x] |
| goal-loop.interrupt-stops-the-loop | [x] | [x] | [x] | [x] | [x] |
