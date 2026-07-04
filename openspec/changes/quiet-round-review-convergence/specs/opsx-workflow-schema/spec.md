# opsx-workflow-schema (delta)

## ADDED Requirements

### Requirement: Review Budget Mode Front Matter

THE review.md front-matter MAY carry a `review_budget_mode` field with controlled vocabulary `quiet-round | land-on-stop`, and WHEN the field is absent consumers SHALL apply `quiet-round` (the autonomous-convergence default), and WHEN the field carries any other value consumers SHALL treat the mode as `land-on-stop` (fail toward the stricter human-in-the-loop behavior, never a silent permissive default), and the field SHALL be read by the orchestration skills only — `opsx gate`'s decision logic is unchanged.

#### Scenario: Absent key defaults to quiet-round
- **WHEN** a change's review.md front-matter carries no review_budget_mode
- **THEN** the orchestration SHALL apply quiet-round semantics (converging rounds continue autonomously)

#### Scenario: Explicit land-on-stop honored
- **WHEN** review.md front-matter sets review_budget_mode to land-on-stop
- **THEN** the orchestration SHALL land for a human ruling at every trajectory/budget stop, as before this change

#### Scenario: Unknown value fails toward the stricter mode
- **IF** review_budget_mode carries a value outside the controlled vocabulary
- **THEN** consumers SHALL treat it as land-on-stop

#### Scenario: Template documents the key
- **WHEN** a new change's review.md is authored from the shipped template
- **THEN** the template SHALL document review_budget_mode (commented or defaulted) alongside review_max_rounds

### Requirement: Migration Sweep Declaration

A change MAY declare retired tokens and forbidden patterns in a machine-readable `sweep.txt` file in its change directory — one extended-regex pattern per line, `#`-prefixed comment lines and blank lines ignored — and THE declared patterns SHALL define the migration-completeness sweep for that change over all git-tracked shipped surfaces, WHERE change-artifact directories (`openspec/changes/**`, including the archive) and ADR history (`adr/**`) are excluded from the swept surface because they legitimately record retired vocabulary.

#### Scenario: Declaration format parsed
- **WHEN** a sweep.txt containing patterns, comments, and blank lines is read
- **THEN** only the non-comment, non-blank lines SHALL be treated as patterns

#### Scenario: History surfaces excluded
- **WHEN** the sweep runs
- **THEN** hits inside openspec/changes/** and adr/** SHALL NOT be reported

#### Scenario: No declaration means no sweep obligation
- **IF** a change directory contains no sweep.txt
- **THEN** the sweep SHALL be a no-op success for that change

### Requirement: Template Mode Table Mirrors Derived Defaults

WHERE the review.md template ships a front-matter mode key commented out so a tier-derived default applies, THE template's human-facing prose table SHALL present that mode's value as derived (naming the derivation), never as a stale literal value that contradicts the derived default.

#### Scenario: Code Review Mode row shows derivation
- **WHEN** the shipped review.md template is read
- **THEN** the Code Review Mode table row SHALL present the value as derived (M ⇒ gating-required, XS/S ⇒ advisory), not the literal `advisory`
