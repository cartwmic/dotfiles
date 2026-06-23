# Capability: opsx-gate-enforcement

## ADDED Requirements

### Requirement: Model Provenance Check

THE opsx-gate command SHALL, for each role that has a configured model (resolved via `opsx-models <role> --json --change <name>` with source != unset/default), enforce the role's delegated-work provenance FAIL-CLOSED: a missing stamp, an unverifiable stamp, or an `actual_model` that does not match the configured model SHALL fail the gate. Matching SHALL be exact on provider-qualified ids (alias table only; no suffix matching). For `review`, every configured review model SHALL have a matching stamp. Where `opsx-models` is unavailable on PATH, the check SHALL fail-closed for any role whose config it cannot resolve rather than silently skipping.

#### Scenario: Configured role with missing stamp fails
- **WHILE** a role model is configured and its work was delegated
- **IF** the produced artifact carries no provenance stamp
- **THEN** opsx-gate SHALL report `model-provenance-missing` and exit non-zero

#### Scenario: Stamped actual model mismatch fails
- **WHILE** a role model is configured
- **IF** the stamped `actual_model` != the configured model (after alias resolution)
- **THEN** opsx-gate SHALL report `model-mismatch` and exit non-zero

#### Scenario: Unconfigured role is not enforced
- **IF** no model is configured for a role (source unset/default)
- **THEN** opsx-gate SHALL NOT enforce a provenance match for that role

#### Scenario: Resolver unavailable is a fatal check
- **WHILE** model-provenance checking is enabled for the change
- **IF** `opsx-models` is not on PATH (the gate cannot determine which roles are configured)
- **THEN** opsx-gate SHALL report a single fatal `model-resolver-unavailable` check and exit non-zero, rather than silently skipping provenance enforcement

### Requirement: In-Session Authoring Marker Check

WHILE the effective `author_in_session` is true or unset, THE opsx-gate command SHALL fail an authoring artifact that carries a delegated model stamp (the original silent-delegation bug), and — while the `author` role specifically has a configured model — SHALL fail an authoring artifact that carries no `authored: in-session` marker. WHILE `author_in_session` is false (opt-in delegation), a delegated author stamp is legitimate and is governed only by the Model Provenance Check (pass on `actual_model` match), not by this marker check.

#### Scenario: Delegated stamp fails while author-in-session
- **WHILE** the effective `author_in_session` is true or unset
- **IF** an authoring artifact carries a delegated model stamp
- **THEN** opsx-gate SHALL report a failed check and exit non-zero (silent delegation caught)

#### Scenario: Opt-out delegated authoring passes on a matching stamp
- **WHILE** `author_in_session` is false and the `author` role is configured
- **WHEN** an authoring artifact carries a delegated author stamp whose `actual_model` matches the configured author model
- **THEN** opsx-gate SHALL NOT fail on the marker check (the Model Provenance Check governs it, and passes)

#### Scenario: Missing marker fails only when author role configured and in-session
- **WHILE** the `author` role has a configured model and `author_in_session` is true/unset
- **IF** an authoring artifact carries no `authored: in-session` marker
- **THEN** opsx-gate SHALL report a failed check and exit non-zero

#### Scenario: No author marker check when author role unconfigured
- **IF** the `author` role has no configured model (source unset/default)
- **THEN** opsx-gate SHALL NOT require an `authored: in-session` marker
