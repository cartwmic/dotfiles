# opsx-workflow-schema — delta for harden-opsx-repo-portability

<!-- authored: in-session -->

## ADDED Requirements

### Requirement: Integration Branch Locator Default Detected

THE review.md template's `**Integration Branch:**` locator field SHALL ship without asserting a hardcoded branch literal as the effective default — the shipped placeholder SHALL direct capture-time detection (the `opsx-cli` `Integration Branch Resolution` order, steps without the locator-field step) to fill the value when apply captures the locator, so a repository whose integration branch is not named `main` records its true branch rather than inheriting a wrong literal.

#### Scenario: Template placeholder directs detection
- **WHEN** the review.md template is inspected as shipped
- **THEN** the `**Integration Branch:**` field SHALL carry a detection-directing placeholder (not a bare branch literal presented as the effective value), documenting that apply fills it via the deterministic resolver at capture time

#### Scenario: Capture in a non-main repo records the true branch
- **WHILE** apply captures the Diff Base + Worktree locator in a repository whose integration branch resolves to `trunk`
- **WHEN** the `**Integration Branch:**` field is written
- **THEN** it SHALL record `trunk` (the resolver's result), and downstream integration-branch-dependent checks SHALL read that committed value first
