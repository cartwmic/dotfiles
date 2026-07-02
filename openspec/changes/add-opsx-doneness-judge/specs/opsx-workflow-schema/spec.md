<!-- authored: in-session -->
# opsx-workflow-schema (delta)

## MODIFIED Requirements

### Requirement: Artifact graph definition

The `opsx-superpowers` schema SHALL declare an 8-artifact graph in dependency order: `proposal` → `specs` → `clarify` → `design` → `analyze` → `review` → `tasks` → `plan`, with an `apply` block that consumes `tasks` (the full graph reachable transitively). The schema SHALL NOT declare `verify`, `retrospective`, `adr`, or `doneness` as artifacts because OpenSpec's `isComplete` is existence-only and would perpetually report incompleteness for optional artifacts; instead the schema SHALL ship templates for these so the opsx-* skills can author them at the appropriate lifecycle moment (apply end for verify, pre-archive for retrospective, archive prompt for ADR promotion, and — when a doneness verdict is required — after the mechanical gate checks pass for doneness).

#### Scenario: Validating the schema
- **WHEN** the user runs `openspec schema validate opsx-superpowers`
- **THEN** validation SHALL pass and the artifact list SHALL include exactly `proposal`, `specs`, `clarify`, `design`, `analyze`, `review`, `tasks`, `plan` (8 artifacts)

#### Scenario: Apply block conforms to OpenSpec types
- **WHEN** the schema's `apply` block is inspected
- **THEN** `apply.requires` SHALL be the array `[tasks]` (the full graph is reachable transitively via `tasks.requires → review → analyze → design → clarify → specs → proposal`); `apply.tracks` SHALL be the single string `tasks.md` (the OpenSpec `ApplyPhaseSchema` zod type requires `tracks: string | null`, never an array)

#### Scenario: ADR + verify + retrospective + doneness templates exist for skill use
- **WHEN** a project uses `schema: opsx-superpowers`
- **THEN** the templates `adr.md`, `verify.md`, `retrospective.md`, and `doneness.md` SHALL be present in the deployed schema's `templates/` directory, AND the schema's `apply.instruction` SHALL document the skill contract for each (who produces them, when, and what enforcement they drive); the `doneness.md` template SHALL define the machine-read fields (`Doneness`, `Gaps`, reviewed range, adapter-stamped reviewer-provenance, frozen-intent hash, Diff Base SHA) that the gate and stall detector parse

### Requirement: Mode switchboard in review.md

The `review.md` artifact SHALL declare a controlled-vocabulary mode switchboard whose values gate apply-time behavior. The required modes SHALL be: `Scale`, `Execution Mode`, `Verification Mode`, `Debug Mode`, `Review Status`, `Delegation Mode`, `Worktree Mode`, `Code Review Mode`, `Loop Max Iterations`, `Spec Level`, and `Doneness Mode`. The default value of `Worktree Mode` SHALL be `worktree-required` for all Scales. THE review.md artifact SHALL additionally carry a machine-readable front-matter block (YAML) at the top of the file mirroring at least `scale`, `worktree_mode`, `verification_mode`, `code_review_mode`, `loop_max_iterations`, `validation_source_mode`, and `doneness_mode`, so that opsx gate reads these values from structured fields rather than scraping the prose mode table. THE `doneness_mode` field SHALL take one of `required` or `waived`, defaulting to `required` for Scale M and above, and WHERE it is `waived` a non-empty `doneness_waiver_rationale` front-matter field SHALL be recorded, mirroring `validation_source_mode`.

#### Scenario: Machine-readable front-matter present
- **WHEN** review.md is authored
- **THEN** its leading YAML front-matter SHALL contain `scale`, `worktree_mode`, `verification_mode`, `code_review_mode`, `loop_max_iterations`, `validation_source_mode`, and `doneness_mode` fields whose values match the prose mode table

#### Scenario: Front-matter is the sole machine source
- **WHEN** opsx gate reads review.md
- **THEN** it SHALL source every mode value from the YAML front-matter ONLY and SHALL NOT parse the prose mode table, which is a non-authoritative human-facing mirror; the schema templates and apply skill are responsible for keeping the table in sync with the front-matter

#### Scenario: Loop Max Iterations defaults by Scale
- **WHEN** review.md is authored without an explicit `Loop Max Iterations`
- **THEN** it SHALL default to a Scale-keyed value (for example S=20, M=40, L=80) and SHALL be recorded in the front-matter as `loop_max_iterations`

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

#### Scenario: Worktree Mode defaults to required
- **WHEN** `review.md` is authored for a change of any Scale without an explicit `Worktree Mode` value
- **THEN** the effective `Worktree Mode` SHALL be `worktree-required`, and `same-tree` SHALL be selectable only as an explicit override

#### Scenario: Worktree Mode forces isolation
- **WHEN** `review.md` declares `Worktree Mode: worktree-required`
- **THEN** every implementation task SHALL execute inside an isolated `git worktree`, AND the main agent (not the subagent) SHALL own writeback of artifact files to the change directory, AND file-contract diffs SHALL use the single immutable `Diff Base SHA` (`git diff --name-only <Diff Base SHA>..HEAD`) recorded by the Worktree Lifecycle Ownership requirement, so per-task commits stay in the diff; there is no separate apply-start `Worktree Base SHA`

#### Scenario: Code Review Mode declared
- **WHEN** `review.md` is authored
- **THEN** it SHALL declare a `Code Review Mode` with one of `none`, `advisory`, or `gating-required`, defaulting to `gating-required` for Scale M and above

#### Scenario: Spec Level pinned to spec-anchored
- **WHEN** the schema is consumed in any new change
- **THEN** the default `Spec Level` in `review.md` SHALL be `spec-anchored`, and selecting `spec-as-source` SHALL produce a warning prompt citing the MDD-era trade-offs documented in the schema's README
