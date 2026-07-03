<!-- authored: in-session -->
# Capability: opsx-workflow-schema

## ADDED Requirements

### Requirement: Review Max Rounds Front Matter

THE review.md front-matter MAY carry a `review_max_rounds` field (positive integer) bounding blind gating review rounds per change, and WHEN the field is absent or unparseable consumers SHALL apply the default of 5, and in this change the field SHALL be read by the orchestration skills only — `opsx gate`'s decision logic is unchanged.

#### Scenario: Absent field defaults
- **WHEN** a change's review.md front-matter carries no review_max_rounds
- **THEN** the orchestration SHALL apply a budget of 5 rounds

#### Scenario: Explicit override honored
- **WHEN** review.md front-matter sets review_max_rounds to a positive integer
- **THEN** the orchestration SHALL use that value as the round budget

#### Scenario: Invalid value falls back
- **IF** review_max_rounds is zero, negative, or non-integer
- **THEN** consumers SHALL treat it as absent and apply the default of 5

### Requirement: Convergence Template Support

THE opsx-superpowers schema templates SHALL ship the convergence-discipline surfaces: the review.md template SHALL include a `Scope Expansions` section and the `review_max_rounds` front-matter key (commented or defaulted), the code-review.md template SHALL include the round-ledger fields and the verdict-contract/rubric header, and the schema SHALL ship a `follow-ups.md` template for out-of-scope finding routing, authored at the lifecycle moment the first out-of-scope finding is routed (not a declared always-required artifact, matching the verify/retrospective/doneness pattern).

#### Scenario: Templates carry the sections
- **WHEN** a new change's review.md and code-review.md are authored from the shipped templates
- **THEN** review.md SHALL contain the Scope Expansions section and code-review.md SHALL contain the round-ledger fields and verdict-contract header

#### Scenario: Follow-ups authored on first routing
- **WHEN** the first out-of-scope finding is routed for a change
- **THEN** follow-ups.md SHALL be created from the shipped template in the change directory

#### Scenario: Absent follow-ups does not fail completeness
- **IF** a change routes no out-of-scope findings
- **THEN** the absence of follow-ups.md SHALL NOT fail schema completeness or the gate

---

## Acceptance criterion quality checklist

| AC ID | Testable | Solution-free | Unambiguous | Consistent | Complete |
|---|---|---|---|---|---|
| opsx-workflow-schema.review-max-rounds-front-matter | [x] | [x] | [x] | [x] | [x] |
| opsx-workflow-schema.convergence-template-support | [x] | [x] | [x] | [x] | [x] |
