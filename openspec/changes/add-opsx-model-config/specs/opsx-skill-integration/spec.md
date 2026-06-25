# Capability: opsx-skill-integration

## ADDED Requirements

### Requirement: Skills honor configured role models

The openspec-loop, openspec-propose, and openspec-apply-change skills SHALL consult the resolved role models when authoring artifacts (author role) and dispatching review subagents (review role) and implementation subagents (impl role), and SHALL fall back to the session model when a role is unset.

#### Scenario: Review subagents use the review models
- **WHEN** a skill dispatches blind review subagents and `review` models are configured (via opsx-models / `OPSX_REVIEW_MODELS`)
- **THEN** it SHALL dispatch one reviewer per configured review model

#### Scenario: Implementation subagents use the impl model
- **WHEN** a skill dispatches an implementation subagent and an `impl` model is configured
- **THEN** that subagent SHALL be dispatched with the configured impl model

#### Scenario: Dispatch honors the resolved provider
- **WHEN** a skill dispatches a review or impl subagent and the resolved value is provider-qualified (`<provider>/<id>`)
- **THEN** the dispatch SHALL pass the provider-qualified value so the subagent runs on the configured provider

#### Scenario: Authoring stays in-session regardless of author model
- **WHILE** `author_in_session` is true or unset
- **WHEN** a skill authors artifacts (even if an `author` model is configured)
- **THEN** it SHALL author in the parent session and SHALL NOT dispatch an authoring subagent; `author_model` is consumed ONLY for delegated authoring when `author_in_session` is false

#### Scenario: Unset roles preserve current behavior
- **IF** a role is unset at every layer
- **THEN** the skill SHALL use the session/default model exactly as before this change
