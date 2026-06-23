# Capability: opsx-post-impl-review

## ADDED Requirements

### Requirement: Post Apply Code Review Artifact

WHILE Code Review Mode is advisory or gating-required, WHEN the implementation checks required before diff review are green (tasks complete, structural checks pass, required validation commands pass, and any retained-required verify is green), THE openspec-apply-change skill SHALL cause a `code-review.md` artifact to be produced by the review subagent (not self-authored by the orchestrator), reviewing the implemented diff against the change's intent and plan, distinct from the pre-implementation analyze review.

#### Scenario: Code review produced when pre-review checks are green
- **WHILE** Code Review Mode is advisory or gating-required
- **WHEN** tasks are complete, structural + required validation checks pass, and any retained-required verify is green
- **THEN** the review subagent SHALL author code-review.md (its body, Verdict, `Diff Base SHA`, reviewed range, `review_mode`, and adapter-stamped provenance field), and the orchestrator skill SHALL only trigger and collect it

#### Scenario: Gating-required does not deadlock under advisory verify
- **WHILE** Code Review Mode is gating-required and Verification Mode is retained-recommended or inline-only
- **WHEN** the pre-review checks (excluding the advisory verify) are green
- **THEN** code-review production SHALL still trigger, so the gate's code-review requirement cannot deadlock waiting on a verify state that the mode does not require

#### Scenario: None mode suppresses production
- **WHILE** Code Review Mode is none
- **WHEN** apply reaches a green verify state
- **THEN** the skill SHALL NOT produce code-review.md

#### Scenario: Diff base resolves for both worktree and same-tree
- **WHEN** the code review computes its diff
- **THEN** the base SHALL be the immutable `Diff Base SHA` recorded in review.md, which apply sets before the first implementation task in both worktree and same-tree modes

#### Scenario: Review baseline is intent plus the full plan
- **WHEN** the code review is performed
- **THEN** the diff SHALL be judged against intent.md together with the proposal, specs, design, plan, and tasks status, so the reviewer can check the implementation followed the approved execution and verification path

### Requirement: Adversarial Review With Degradation

THE code-review production SHALL use the adversarial-review capability over the diff when that capability is available, and IF no adversarial-review capability is registered, THEN it SHALL fall back to a single-model review and SHALL mark code-review.md as degraded.

#### Scenario: Adversarial path used when available
- **WHERE** the adversarial-review capability resolves to a registered skill
- **WHEN** code review runs
- **THEN** the review SHALL be conducted blind over the diff and the converged findings SHALL be recorded in code-review.md

#### Scenario: Degraded single-model fallback
- **IF** no adversarial-review capability is registered
- **THEN** code-review.md SHALL still be produced, SHALL set `review_mode: degraded-single-model`, and SHALL carry a degraded-mode notice in its header

#### Scenario: Degraded review does not satisfy Constitution IX
- **WHILE** the change modifies an existing skill (Constitution IX) or runs without a subagent-dispatch adapter
- **IF** code-review.md `review_mode` is degraded-single-model
- **THEN** opsx-gate and archive SHALL treat the code-review check as failed, since a self-authored or single-model review does not satisfy the multi-model adversarial requirement

### Requirement: Code Review Mode Switchboard

THE review.md mode switchboard SHALL declare a `Code Review Mode` with values `none`, `advisory`, and `gating-required`, defaulting to gating-required for Scale M and above and to advisory for Scale S.

#### Scenario: Mode default by Scale
- **WHEN** review.md is authored for a Scale M change without an explicit Code Review Mode
- **THEN** the mode SHALL default to gating-required

#### Scenario: Advisory mode does not block
- **WHILE** Code Review Mode is advisory
- **WHEN** code-review.md records a fail Verdict
- **THEN** archive SHALL be permitted, opsx-gate SHALL NOT fail on the code-review check, and the failing findings SHALL be surfaced as warnings

### Requirement: Archive Gate On Code Review

WHILE Code Review Mode is gating-required, THE openspec-archive-change skill SHALL refuse to archive the change unless code-review.md exists with a Verdict of pass.

#### Scenario: Missing or failing review blocks archive
- **WHILE** Code Review Mode is gating-required
- **IF** code-review.md is absent or its Verdict is not pass
- **THEN** archive SHALL be refused and the reason SHALL be reported

#### Scenario: Passing review permits archive
- **WHILE** Code Review Mode is gating-required
- **WHEN** code-review.md exists with a pass Verdict
- **THEN** archive SHALL proceed subject to the other archive gates

---

## Acceptance criterion quality checklist

| AC ID | Testable | Solution-free | Unambiguous | Consistent | Complete |
|---|---|---|---|---|---|
| opsx-post-impl-review.post-apply-code-review-artifact | [x] | [x] | [x] | [x] | [x] |
| opsx-post-impl-review.adversarial-review-with-degradation | [x] | [x] | [x] | [x] | [x] |
| opsx-post-impl-review.code-review-mode-switchboard | [x] | [x] | [x] | [x] | [x] |
| opsx-post-impl-review.archive-gate-on-code-review | [x] | [x] | [x] | [x] | [x] |
