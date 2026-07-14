<!-- authored: in-session -->
# Capability: opsx-model-config

## ADDED Requirements

### Requirement: Thinking Suffix Passthrough

THE opsx models resolver and configuration surfaces SHALL treat a trailing pi
thinking/effort suffix on a model id (`:<level>` where `<level>` is one of
`off`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`) as part of the model
id string. Slash-containing values that include such a suffix SHALL still be
returned VERBATIM (provider keys SHALL NOT re-qualify or strip the suffix).
Bare ids with a suffix and a configured provider SHALL qualify as
`<provider>/<id>:<level>` (suffix retained after qualification). Consumers
(loop export, subagent `model:` field) receive the suffix-bearing string so pi
may honor thinking without separate opsx effort keys.

#### Scenario: Slash-qualified id with suffix is verbatim
- **WHEN** a role is configured to `cursor/composer-2.5:high`
- **THEN** `opsx models <role>` SHALL print `cursor/composer-2.5:high`
  unchanged

#### Scenario: Bare id with suffix is provider-qualified retaining suffix
- **WHILE** the top-level default `provider` is `claude-bridge` and a role is
  set to `claude-opus-4-8:xhigh`
- **THEN** the resolved value SHALL be `claude-bridge/claude-opus-4-8:xhigh`

#### Scenario: Review list entries keep per-entry suffixes
- **WHEN** `review` is configured as a list containing
  `anthropic/claude-sonnet-5:high` and `cursor/composer-2.5:low`
- **THEN** `opsx models review` SHALL print each entry on its own line with
  its suffix preserved

## MODIFIED Requirements
<!-- none — Role Model Resolver / Layered Resolution Order / Config Conventions
remain authoritative; Thinking Suffix Passthrough adds the suffix contract
without restating those requirements. -->

## REMOVED Requirements
<!-- none -->

## RENAMED Requirements
<!-- none -->

---

## Acceptance criterion quality checklist

| AC ID | Testable | Solution-free | Unambiguous | Consistent | Complete |
|---|---|---|---|---|---|
| opsx-model-config.thinking-suffix-passthrough | [x] | [x] | [x] | [x] | [x] |
