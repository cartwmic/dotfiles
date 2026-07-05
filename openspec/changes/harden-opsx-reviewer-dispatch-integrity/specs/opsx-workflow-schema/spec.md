# opsx-workflow-schema (delta)

## MODIFIED Requirements

### Requirement: Convergence Template Support

THE opsx-superpowers schema templates SHALL ship the convergence-discipline surfaces: the review.md template SHALL include a `Scope Expansions` section and the `review_max_rounds` front-matter key (commented or defaulted), the code-review.md template SHALL include the round-ledger fields, the verdict-contract/rubric header, and an own-line `**Attested HEAD:**` field documented as gate-read verbatim (with the reviewer attestation preamble — `Attested HEAD:` + `Attested Path:` as the reviewer's first findings-output lines — stated in the embedded dispatch contract), the doneness.md template SHALL include the same `**Attested HEAD:**` field for the independently dispatched judge path, and the schema SHALL ship a `follow-ups.md` template for out-of-scope finding routing, authored at the lifecycle moment the first out-of-scope finding is routed (not a declared always-required artifact, matching the verify/retrospective/doneness pattern).

#### Scenario: Templates carry the sections
- **WHEN** a new change's review.md and code-review.md are authored from the shipped templates
- **THEN** review.md SHALL contain the Scope Expansions section and code-review.md SHALL contain the round-ledger fields, the verdict-contract header, and the `**Attested HEAD:**` field

#### Scenario: Dispatch contract states the attestation preamble
- **WHEN** the code-review.md template's embedded verdict-contract/dispatch text is read
- **THEN** it SHALL state that every blind reviewer records `Attested HEAD:` and `Attested Path:` as its first findings-output lines before reviewing

#### Scenario: Doneness template carries the field
- **WHEN** doneness.md is filled from the shipped template for an independently dispatched full_rigor judge
- **THEN** the template SHALL provide the `**Attested HEAD:**` own-line field

#### Scenario: Follow-ups authored on first routing
- **WHEN** the first out-of-scope finding is routed for a change
- **THEN** follow-ups.md SHALL be created from the shipped template in the change directory

#### Scenario: Absent follow-ups does not fail completeness
- **IF** a change routes no out-of-scope findings
- **THEN** the absence of follow-ups.md SHALL NOT fail schema completeness or the gate
