# Capability: opsx-workflow-schema

## ADDED Requirements

### Requirement: Review front-matter carries role models

THE review.md front-matter SHALL optionally carry `author_model` (string), `review_models` (string or list), and `impl_model` (string), giving per-change overrides that the opsx-models resolver reads above the project and user config files.

#### Scenario: Per-change model override recorded
- **WHEN** review.md front-matter sets `author_model`, `review_models`, or `impl_model`
- **THEN** `opsx-models <role> --change <name>` SHALL return those values above the project/user files

#### Scenario: Front-matter model fields are optional
- **IF** the front-matter omits the model fields
- **THEN** the schema SHALL remain valid and the resolver SHALL fall through to the project/user/default layers

### Requirement: Author-in-session front-matter flag

THE review.md front-matter SHALL optionally carry `author_in_session` (boolean, default true). WHILE it is true or unset, artifact authoring SHALL remain in the parent session and SHALL NOT be delegated to an authoring subagent.

#### Scenario: Default keeps authoring in-session
- **IF** `author_in_session` is unset
- **THEN** the effective value SHALL be true and authoring SHALL NOT be delegated

#### Scenario: Explicit opt-out permits delegation
- **WHILE** `author_in_session` is false
- **WHEN** authoring runs
- **THEN** authoring MAY be delegated to a subagent dispatched with the configured author model
