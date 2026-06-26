<!-- authored: in-session -->
# Capability: opsx-skill-integration

Delta for consolidate-opsx-cli: migrate command-name references from the retired
standalone executables to the unified `opsx <subcommand>` form. Behavior is unchanged;
only the invocation surface is renamed (the executables are removed by this change, so
the spec-of-record must name commands that exist). Full requirement content restated
per the MODIFIED-delta rule.

## MODIFIED Requirements

### Requirement: openspec-loop orchestrator skill exists

A new skill SHALL be created at `dot_local/share/agent-harness/canonical/skills/openspec-loop/SKILL.md` implementing the single-orchestrator loop that advances an opsx-superpowers change until opsx gate is green, delegating review steps to subagents per the opsx-loop-orchestration capability.

#### Scenario: Skill metadata complete
- **WHEN** the skill is loaded by a harness
- **THEN** its frontmatter SHALL include `name: openspec-loop`, a one-line `description`, `license`, and `compatibility`, and the body SHALL describe the gate-driven cycle and the subagent-review-against-baseline rule

#### Scenario: Skill deploys cross-harness
- **WHEN** `chezmoi apply` runs followed by the harness-config apply step
- **THEN** the skill SHALL be symlinked into every harness skills directory as `openspec-loop`, consistent with the canonical-skill deployment pattern

#### Scenario: Kickoff adapter carries no workflow logic
- **WHEN** a harness-specific kickoff (such as a pi extension command) invokes the loop
- **THEN** that adapter SHALL only wire the worker to the openspec-loop skill and the judge to opsx gate, and removing the adapter SHALL NOT remove any workflow logic

### Requirement: Skills honor configured role models

The openspec-loop, openspec-propose, and openspec-apply-change skills SHALL consult the resolved role models when authoring artifacts (author role) and dispatching review subagents (review role) and implementation subagents (impl role), and SHALL fall back to the session model when a role is unset.

#### Scenario: Review subagents use the review models
- **WHEN** a skill dispatches blind review subagents and `review` models are configured (via opsx models / `OPSX_REVIEW_MODELS`)
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

