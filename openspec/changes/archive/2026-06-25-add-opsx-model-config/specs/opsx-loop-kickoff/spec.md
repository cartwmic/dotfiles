# Capability: opsx-loop-kickoff

## ADDED Requirements

### Requirement: Loop exports resolved role models

WHEN the opsx-loop extension starts a loop for a change, THE extension SHALL resolve the roles by invoking `opsx-models <role> --json --change <name>` (NOT by parsing config itself, so it matches the gate's resolution) and export `OPSX_AUTHOR_MODEL`, `OPSX_REVIEW_MODELS`, `OPSX_IMPL_MODEL`, and `OPSX_AUTHOR_IN_SESSION` into the worker turns it injects, so the skills' authoring and subagent dispatch pick them up. The exported model values SHALL be provider-resolved (provider-qualified where a provider is configured). The extension SHALL remain a consumer — it SHALL NOT be the source of truth for the config.

#### Scenario: Models exported on loop start
- **WHEN** the user starts `/opsx-loop <change>` and role models are configured
- **THEN** the injected worker turns SHALL see `OPSX_AUTHOR_MODEL`, `OPSX_REVIEW_MODELS`, `OPSX_IMPL_MODEL`, and `OPSX_AUTHOR_IN_SESSION` set to values resolved WITH `--change <name>` (provider-qualified where a provider is configured, so per-change front-matter is honored and matches the gate)

#### Scenario: Unset config does not break the loop
- **IF** no role models are configured at any layer
- **THEN** the extension SHALL start the loop normally with the variables unset/defaulted, and behavior SHALL match the pre-change loop

#### Scenario: Config survives extension removal
- **WHEN** the opsx-loop extension is removed
- **THEN** the model config and the opsx-models resolver SHALL remain usable by the bash driver and other harnesses
