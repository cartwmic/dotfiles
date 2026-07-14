<!-- authored: in-session -->
# Capability: opsx-model-config

## ADDED Requirements
<!-- none — narrows the delegated-honor clause on Author In Session By Default -->

## MODIFIED Requirements

### Requirement: Author In Session By Default

THE workflow SHALL author artifacts in the parent session (its model) by
default, and SHALL NOT delegate authoring unless `author_in_session` is
explicitly false. The in-session authoring STEP SHALL write an
`authored: in-session` marker on artifacts it authors, and `opsx gate` SHALL
fail an authoring artifact that carries no authoring marker while the
`author` role specifically has a configured model and `author_in_session` is
true/unset. The marker is a cheap SELF-ATTESTED tripwire for the observed bug
(silent authoring delegation would not run the in-session marker step); it is
NOT model provenance — this change does not attempt to enforce delegated
model provenance via a post-hoc gate (a same-UID actor can write any file the
gate reads).

WHILE an `/opsx-loop` session is armed, delegated review/impl/opt-out-author
dispatch SHALL bind the resolved role model mechanically through the
`opsx_dispatch` surface (role is sole source; unset role refuses; no session
fallback on that path). Outside an armed loop, delegated review/impl/opt-out-
author dispatch that uses the generic subagent path remains best-effort (not
gate-verified). Gate verification of sealed provenance model ids against
resolved role config remains out of scope for this requirement.

#### Scenario: Authoring is not delegated by default
- **WHILE** `author_in_session` is unset or true
- **WHEN** an artifact is authored
- **THEN** it SHALL be authored in the parent session, SHALL NOT dispatch an
  authoring subagent, and the in-session authoring step SHALL write an
  `authored: in-session` marker

#### Scenario: Missing in-session marker fails the gate
- **WHILE** `author_in_session` is true/unset and the `author` role is configured
- **IF** an authoring artifact carries no `authored: in-session` marker
- **THEN** opsx gate SHALL report a failed check and exit non-zero

#### Scenario: Armed-loop delegated dispatch is mechanically bound
- **WHILE** an `/opsx-loop` session is armed and a review or impl role is
  configured
- **WHEN** delegated work for that role is dispatched
- **THEN** the spawn SHALL use the resolved role model via `opsx_dispatch`
  (caller model ignored); the gate still does not post-hoc verify provenance
  model ids against config

#### Scenario: Opt-in authoring delegation under armed loop
- **WHILE** `author_in_session` is false, an `author` model is configured,
  and a loop is armed
- **WHEN** authoring is delegated
- **THEN** the authoring spawn SHALL go through `opsx_dispatch` with
  `role: "author"` and the resolved author model; the gate does not require
  the in-session marker and does not verify the delegated model id post-hoc

#### Scenario: Disarmed delegated dispatch remains best-effort
- **WHILE** no loop is armed and an `impl` (or review/author) model is configured
- **WHEN** delegated work uses the generic subagent path
- **THEN** the configured model is passed best-effort and is not gate-verified

## REMOVED Requirements
<!-- none -->

## RENAMED Requirements
<!-- none -->

---

## Acceptance criterion quality checklist

| AC ID | Testable | Solution-free | Unambiguous | Consistent | Complete |
|---|---|---|---|---|---|
| opsx-model-config.author-in-session-by-default | [x] | [x] | [x] | [x] | [x] |
