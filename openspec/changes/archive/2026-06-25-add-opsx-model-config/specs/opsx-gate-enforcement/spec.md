# Capability: opsx-gate-enforcement

## ADDED Requirements

### Requirement: In-Session Authoring Marker Check

WHILE the effective `author_in_session` is true or unset AND the `author` role specifically has a configured model, THE opsx-gate command SHALL fail an authoring artifact that carries no `authored: in-session` marker. The marker SHALL be the literal line `<!-- authored: in-session -->` present anywhere in the artifact file (an HTML comment so it is inert in rendered Markdown); the gate detects it by a plain substring/line scan of the file. The marker is written in-session by the authoring step; it is a cheap, SELF-ATTESTED tripwire for the observed bug (authoring silently delegated, which would NOT run the in-session marker step) — it is NOT proof of the session model, and a worker that both delegates AND forges the marker is out of the threat model (a post-hoc gate cannot force a model against a same-UID actor). The authoring-artifact set the marker check scans SHALL be exactly: `proposal.md`, `intent.md`, `design.md`, `clarify.md`, `tasks.md`, `plan.md`, and the change's `specs/**/spec.md` (NOT `review.md`, `verify.md`, `code-review.md`, `analyze.md`, or `retrospective.md`). WHILE `author_in_session` is false (opt-in delegation), the marker is not required.

#### Scenario: Missing marker fails only when author role configured and in-session
- **WHILE** the `author` role has a configured model and `author_in_session` is true/unset
- **IF** an authoring artifact lacks the literal line `<!-- authored: in-session -->`
- **THEN** opsx-gate SHALL report a failed check and exit non-zero

#### Scenario: No author marker check when author role unconfigured
- **IF** the `author` role has no configured model (source unset/default)
- **THEN** opsx-gate SHALL NOT require an `authored: in-session` marker

#### Scenario: Opt-out delegation does not require the marker
- **WHILE** `author_in_session` is false
- **WHEN** authoring is delegated
- **THEN** opsx-gate SHALL NOT require an `authored: in-session` marker on the authoring artifacts
