# opsx-workflow-schema (delta)

## ADDED Requirements

### Requirement: Design Fidelity Artifact Template

THE schema SHALL ship a `templates/design-fidelity.md` template for the sealed fidelity verdict: a per-AC verdict table (AC reference, `entailed | not-entailed | not-covered`, evidence), an own-line `**Fidelity:**` overall field (`delivered | violated`), judge-provenance and `**Attested HEAD:**` fields, digest-binding fields for intent.md, design.md, and every delta spec file (sha256 each, one own-line field per file with its path), an optional human-waiver field written only by a human ruling at the decision-audit landing, and template comments documenting the bounded judge contract and the full-sweep re-judge rule. Gate-read fields SHALL be own-line `**Field:** value` form with multi-line-only HTML comments (single-line comments break the comment-stripper).

#### Scenario: Template ships the sealed-verdict contract
- **WHEN** the shipped design-fidelity.md template is inspected
- **THEN** it SHALL carry the per-AC verdict table, the `Fidelity` field, judge provenance, `Attested HEAD`, per-file digest-binding fields, and the documented bounded contract + full-sweep re-judge rule

#### Scenario: Judges fill the shipped template
- **WHEN** a fidelity judgment is sealed
- **THEN** the artifact SHALL be produced by filling the shipped template (never free-written), mirroring the verdict-template discipline of code-review.md and doneness.md

## MODIFIED Requirements

### Requirement: Mode switchboard in review.md

The `review.md` artifact SHALL declare a controlled-vocabulary mode switchboard whose values gate apply-time behavior. The required modes SHALL be: `Scale`, `Execution Mode`, `Verification Mode`, `Debug Mode`, `Review Status`, `Delegation Mode`, `Code Review Mode`, `Loop Max Iterations`, `Spec Level`, and `Doneness Mode`. There SHALL be NO `Worktree Mode`: worktree execution is the only execution model at every Scale — the schema, template, and prose table SHALL NOT present a worktree mode, and a review.md front-matter declaring a `worktree_mode` key SHALL be rejected fail-closed by the gate (opsx-gate-enforcement Worktree Mandatory Gate Enforcement). THE review.md artifact SHALL additionally carry a machine-readable front-matter block (YAML) at the top of the file mirroring at least `scale`, `full_rigor`, `verification_mode`, `code_review_mode`, `loop_max_iterations`, `validation_source_mode`, and `doneness_mode`, so that opsx gate reads these values from structured fields rather than scraping the prose mode table. THE `doneness_mode` field SHALL take one of `required` or `waived`, defaulting to `required` for Scale M and above, and WHERE it is `waived` a non-empty `doneness_waiver_rationale` front-matter field SHALL be recorded, mirroring `validation_source_mode`.

#### Scenario: Machine-readable front-matter present
- **WHEN** review.md is authored
- **THEN** its leading YAML front-matter SHALL contain `scale`, `full_rigor`, `verification_mode`, `code_review_mode`, `loop_max_iterations`, `validation_source_mode`, and `doneness_mode` fields whose values match the prose mode table, and SHALL NOT contain a `worktree_mode` key

#### Scenario: Front-matter is the sole machine source
- **WHEN** opsx gate reads review.md
- **THEN** it SHALL source every mode value from the YAML front-matter ONLY and SHALL NOT parse the prose mode table, which is a non-authoritative human-facing mirror; the schema templates and apply skill are responsible for keeping the table in sync with the front-matter

#### Scenario: Loop Max Iterations defaults by tier
- **WHEN** review.md is authored without an explicit `Loop Max Iterations`
- **THEN** it SHALL default to an `XS|S|M`-keyed value (for example XS=10, S=20, M=40), a `full_rigor: true` change SHALL be granted the former L budget (for example 80), and the value SHALL be recorded in the front-matter as `loop_max_iterations`

#### Scenario: Doneness Mode defaults to required at Scale M and above
- **WHEN** review.md is authored for a change of Scale M or above without an explicit `doneness_mode`
- **THEN** the effective `doneness_mode` SHALL be `required`, and it SHALL be recorded in the front-matter as `doneness_mode`

#### Scenario: Doneness Mode waiver records a rationale
- **WHEN** review.md declares `doneness_mode: waived`
- **THEN** a non-empty `doneness_waiver_rationale` SHALL be recorded in review.md front-matter, and opsx gate SHALL NOT require a doneness verdict for the change ONLY WHILE that rationale is present and non-empty

#### Scenario: Verification Mode gates verify.md retention
- **WHEN** `review.md` declares `Verification Mode: retained-required`
- **THEN** `verify.md` SHALL be a required artifact for apply completion, and `openspec-archive-change` SHALL refuse to proceed unless `verify.md` exists and its Completion Decision is green

#### Scenario: Debug Mode gates systematic-debugging sections
- **WHEN** `review.md` declares `Debug Mode: systematic-debugging`
- **THEN** `plan.md` SHALL contain `Observed Failure` and `Debugging Trail` sections, and these SHALL be populated before any code-modifying task is started

#### Scenario: Delegation Mode dispatches via the subagent-dispatch capability hook
- **WHEN** `review.md` declares `Delegation Mode: subagent-eligible`
- **THEN** the `openspec-apply-change` skill SHALL dispatch each implementation task through the registered subagent-dispatch capability adapter when one exists, and SHALL degrade to inline execution with a recorded notice when none is registered (pi-subagents is the pi adapter, not a schema-level requirement)
- **WHEN** `review.md` declares `Delegation Mode: subagent-required`
- **THEN** the skill SHALL fail with an actionable error if no subagent-dispatch adapter is registered, rather than silently executing inline

#### Scenario: Worktree isolation is unconditional
- **WHEN** apply begins for ANY change at ANY Scale
- **THEN** every implementation task SHALL execute inside an isolated `git worktree` on branch `opsx/<change>` (created via `opsx worktree ensure`), the main agent (not the subagent) SHALL own writeback of artifact files to the change directory, AND file-contract diffs SHALL use the single immutable `Diff Base SHA` (`git diff --name-only <Diff Base SHA>..HEAD`) recorded by the Worktree Lifecycle Ownership requirement

#### Scenario: Declared worktree_mode key is rejected
- **IF** review.md front-matter declares a `worktree_mode` key with any value
- **THEN** the gate SHALL fail closed naming the key's removal and the delete-the-key remedy, never honoring or silently ignoring the key

#### Scenario: Code Review Mode declared
- **WHEN** `review.md` is authored
- **THEN** it SHALL declare a `Code Review Mode` with one of `none`, `advisory`, or `gating-required`, defaulting to `gating-required` for Scale M and above

#### Scenario: Spec Level pinned to spec-anchored
- **WHEN** the schema is consumed in any new change
- **THEN** the default `Spec Level` in `review.md` SHALL be `spec-anchored`, and selecting `spec-as-source` SHALL produce a warning prompt citing the MDD-era trade-offs documented in the schema's README
