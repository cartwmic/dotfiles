<!-- authored: in-session -->

# Capability: opsx-loop

## ADDED Requirements

### Requirement: TUI scenarios exercise user-visible slash commands

THE opsx-loop test suite SHALL exercise the user-facing `/opsx-loop` command paths in a real Pi TUI and SHALL assert pane-visible feedback for each command, so regressions where handlers return discarded strings instead of notifying are caught.

#### Scenario: Status and bare command are visible
- **WHEN** the scenario driver sends `/opsx-loop` and `/opsx-loop status` into a real Pi TUI with no active loop
- **THEN** the suite SHALL assert that the pane shows a no-active-loop notification

#### Scenario: Clear command is visible
- **WHEN** the scenario driver sends `/opsx-loop clear` into a real Pi TUI with no active loop
- **THEN** the suite SHALL assert that the pane shows a no-active-loop-to-clear notification

#### Scenario: Models subcommand preserves arguments
- **WHEN** the scenario driver sends `/opsx-loop models set author claude-bridge/claude-haiku-4-5` into a real Pi TUI
- **THEN** the suite SHALL assert that the fake `opsx models` command receives `set author claude-bridge/claude-haiku-4-5` intact and that its output is visible in the pane

### Requirement: TUI scenarios exercise deterministic loop states

THE opsx-loop test suite SHALL run deterministic TUI scenarios for green gates, red gates, status, clear, goal distillation, and loop hold/re-arm without requiring real hosted model calls in the default run.

#### Scenario: Already-green change does not arm
- **WHEN** the scenario driver sends `/opsx-loop <change>` for a temp change whose fake `opsx gate` exits zero
- **THEN** the suite SHALL assert that the pane reports the change ready to archive and that no worker turn is injected

#### Scenario: Red change arms and can be cleared
- **WHEN** the scenario driver sends `/opsx-loop <change>` for a temp change whose fake `opsx gate` exits non-zero
- **THEN** the suite SHALL assert that the pane reports an active loop, a worker directive is injected, `/opsx-loop status` names the active change, and `/opsx-loop clear` prevents further continuation

#### Scenario: Goal distill pauses for intent confirmation
- **WHEN** the scenario driver sends `/opsx-loop goal build a multi word thing` and the fake agent turn creates a new change with `intent.md`
- **THEN** the suite SHALL assert that the full goal text reaches the distill directive, the loop stops, and the pane names the new intent path awaiting confirmation

#### Scenario: Loop hold stops continuation and named re-arm clears it
- **WHILE** a temp change has `loop_hold: true` and a non-empty `loop_hold_reason` in `review.md`
- **WHEN** the scenario driver reaches an `agent_end` continuation point and then sends `/opsx-loop <change>` again
- **THEN** the suite SHALL assert that continuation stops with the hold reason, named re-arm clears the hold state, and the re-arm notification includes the previous reason

### Requirement: Scenario harness is isolated and signal-driven

THE opsx-loop TUI scenario harness SHALL isolate each scenario from the user's real Pi sessions and OpenSpec workspace, and SHALL wait on explicit signals rather than fixed sleeps for scenario completion.

#### Scenario: Private tmux server per scenario
- **WHEN** a scenario starts
- **THEN** the harness SHALL create a unique tmux server/socket for that scenario and tear it down after pass, fail, or timeout without using broad process kills

#### Scenario: Temp repo and fake commands isolate state
- **WHEN** a scenario runs
- **THEN** the harness SHALL use a temp repo and prepend fake `opsx`/fixture commands to `PATH`, recording argv, cwd, and relevant env for assertions without mutating the user's real OpenSpec changes

#### Scenario: Completion waits use observable signals
- **WHEN** a scenario waits for Pi, a command result, a fake provider turn, or a fake `opsx` invocation
- **THEN** the harness SHALL wait for pane regexes or fixture log counters before asserting outcomes, with only minimal draw-settle sleeps after a signal

#### Scenario: Real-model smoke is opt-in
- **IF** a real-provider smoke scenario is present
- **THEN** the default runner SHALL skip it unless an explicit environment flag enables it, and SHALL document required credentials and flake/cost trade-offs

---

## Acceptance criterion quality checklist

| AC ID | Testable | Solution-free | Unambiguous | Consistent | Complete |
|---|---|---|---|---|---|
| opsx-loop.tui-scenarios-exercise-user-visible-slash-commands | [x] | [x] | [x] | [x] | [x] |
| opsx-loop.tui-scenarios-exercise-deterministic-loop-states | [x] | [x] | [x] | [x] | [x] |
| opsx-loop.scenario-harness-is-isolated-and-signal-driven | [x] | [x] | [x] | [x] | [x] |
