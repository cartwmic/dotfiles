# Capability: goal-loop

## ADDED Requirements

### Requirement: Pluggable Command Judge

THE goal-loop SHALL support a judge configured as a shell command in addition to the existing model evaluator, and WHERE a command judge is configured, THE goal-loop SHALL execute that command after each worker turn, treat exit 0 as the condition met, and treat any non-zero exit as not met with the command's output surfaced as the reason. The goal-loop SHALL remain agnostic to what the command checks.

#### Scenario: Command judge reports met
- **WHERE** a command judge is configured
- **WHEN** a worker turn completes and the judge command exits 0
- **THEN** the goal-loop SHALL treat the condition as met, stop continuing turns, and notify the user

#### Scenario: Command judge reports not met
- **WHERE** a command judge is configured
- **WHEN** a worker turn completes and the judge command exits non-zero
- **THEN** the goal-loop SHALL treat the condition as not met and SHALL carry the command's output as the directive for the next worker turn

#### Scenario: Model judge remains the default
- **WHERE** no command judge is configured
- **WHEN** a worker turn completes
- **THEN** the goal-loop SHALL evaluate the condition with the model evaluator exactly as before this change

#### Scenario: Judge command failure is non-fatal
- **WHERE** a command judge is configured
- **IF** the judge command cannot be executed at all
- **THEN** the goal-loop SHALL treat the condition as not yet met, surface an explanatory reason, and continue without terminating the session abnormally

#### Scenario: Command judge has a defined configuration point
- **WHEN** a user or orchestrator configures a command judge
- **THEN** the goal-loop SHALL accept the judge command through its existing configuration precedence (config file, overridden by environment variable, falling back to the model evaluator when unset), consistent with how the judge model and turn budget are already configured

## MODIFIED Requirements

### Requirement: Judge Each Completed Turn

WHILE a goal is active, WHEN a worker turn completes, THE goal-loop SHALL evaluate the active condition using the configured judge. WHERE the judge is the model evaluator, it SHALL consider only content already surfaced in the conversation transcript, using an evaluator distinct from the worker, and obtain a met-or-not result with a short reason. WHERE the judge is a command, it SHALL instead evaluate external state by the command's exit code (the command MAY inspect the filesystem and git state outside the transcript), treating exit 0 as met and non-zero as not met.

#### Scenario: Model judge evaluates from the transcript only
- **WHILE** a goal is active and no command judge is configured
- **WHEN** a worker turn completes
- **THEN** the active condition and the conversation transcript are evaluated by a separate model evaluator considering only transcript content, producing a met flag and a reason

#### Scenario: Command judge evaluates external state
- **WHILE** a goal is active and a command judge is configured
- **WHEN** a worker turn completes
- **THEN** the command judge MAY inspect filesystem and git state outside the transcript, and its exit code SHALL determine the met result

---

## Acceptance criterion quality checklist

| AC ID | Testable | Solution-free | Unambiguous | Consistent | Complete |
|---|---|---|---|---|---|
| goal-loop.pluggable-command-judge | [x] | [x] | [x] | [x] | [x] |
| goal-loop.judge-each-completed-turn | [x] | [x] | [x] | [x] | [x] |
