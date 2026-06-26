<!-- authored: in-session -->
# Capability: opsx-workflow-schema

Delta for consolidate-opsx-cli: migrate command-name references from the retired
standalone executables to the unified `opsx <subcommand>` form. Behavior is unchanged;
only the invocation surface is renamed (the executables are removed by this change, so
the spec-of-record must name commands that exist). Full requirement content restated
per the MODIFIED-delta rule.

## MODIFIED Requirements

### Requirement: Mode switchboard in review.md

The `review.md` artifact SHALL declare a controlled-vocabulary mode switchboard whose values gate apply-time behavior. The required modes SHALL be: `Scale`, `Execution Mode`, `Verification Mode`, `Debug Mode`, `Review Status`, `Delegation Mode`, `Worktree Mode`, `Code Review Mode`, `Loop Max Iterations`, and `Spec Level`. The default value of `Worktree Mode` SHALL be `worktree-required` for all Scales. THE review.md artifact SHALL additionally carry a machine-readable front-matter block (YAML) at the top of the file mirroring at least `scale`, `worktree_mode`, `verification_mode`, `code_review_mode`, `loop_max_iterations`, and `validation_source_mode`, so that opsx gate reads these values from structured fields rather than scraping the prose mode table.

#### Scenario: Machine-readable front-matter present
- **WHEN** review.md is authored
- **THEN** its leading YAML front-matter SHALL contain `scale`, `worktree_mode`, `verification_mode`, `code_review_mode`, and `loop_max_iterations` fields whose values match the prose mode table

#### Scenario: Front-matter is the sole machine source
- **WHEN** opsx gate reads review.md
- **THEN** it SHALL source every mode value from the YAML front-matter ONLY and SHALL NOT parse the prose mode table, which is a non-authoritative human-facing mirror; the schema templates and apply skill are responsible for keeping the table in sync with the front-matter

#### Scenario: Loop Max Iterations defaults by Scale
- **WHEN** review.md is authored without an explicit `Loop Max Iterations`
- **THEN** it SHALL default to a Scale-keyed value (for example S=20, M=40, L=80) and SHALL be recorded in the front-matter as `loop_max_iterations`

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

### Requirement: Worktree Lifecycle Ownership

THE schema's apply and archive instructions SHALL own the full worktree lifecycle for a change: creating an isolated worktree on a branch named `opsx/<change>` before implementation, capturing the base SHA, and merging then removing the worktree at archive only after the gate is green.

#### Scenario: Worktree created before implementation
- **WHEN** apply begins for a change whose effective Worktree Mode is worktree-required
- **THEN** a worktree on branch `opsx/<change>` SHALL exist before any implementation task runs, and its base SHA SHALL be recorded in review.md

#### Scenario: Diff base is immutable per implementation branch
- **WHEN** the `opsx/<change>` worktree is first created
- **THEN** apply SHALL record `Diff Base SHA` as the integration-branch merge-base (not apply-start HEAD), plus `Worktree Path` and `Integration Branch`, into review.md, and these SHALL NOT change for the life of the branch

#### Scenario: Existing branch from a prior aborted apply is reused
- **WHILE** a branch `opsx/<change>` already exists from a prior run
- **WHEN** apply begins
- **THEN** apply SHALL reuse the existing worktree/branch and SHALL preserve the previously recorded `Diff Base SHA`; IF that base is absent or is not an ancestor of `opsx/<change>`, apply SHALL halt for human repair rather than re-recording a base that would exclude unverified commits

#### Scenario: Worktree creation failure aborts apply
- **IF** `git worktree add` fails for any reason (path conflict, detached HEAD, insufficient space, permission)
- **THEN** apply SHALL abort with an actionable error and SHALL NOT proceed to any implementation task

#### Scenario: Budget exhaustion preserves the worktree
- **WHILE** a worktree exists
- **IF** the loop stops because its iteration budget is exhausted
- **THEN** the worktree and its `opsx/<change>` branch SHALL be preserved for inspection and SHALL NOT be removed

#### Scenario: Same-tree records a Diff Base SHA too
- **WHILE** Worktree Mode is the explicit same-tree override (no `opsx/<change>` worktree)
- **WHEN** apply begins
- **THEN** apply SHALL record `Diff Base SHA` as the current repo HEAD before the first implementation task, leave `Worktree Path` empty, and opsx gate's freshness locator SHALL resolve the implementation HEAD as the current repo HEAD (no `opsx/<change>` branch required)

#### Scenario: Worktree merged and removed at archive
- **WHEN** archive proceeds for a change implemented in a worktree
- **THEN** the `opsx/<change>` branch SHALL be landed onto the named integration branch using the configured strategy and the worktree SHALL be removed, and this SHALL occur only after opsx gate reports green

#### Scenario: Post-green merge conflict aborts archive safely
- **WHILE** opsx gate is green
- **IF** landing the branch fails because the integration branch advanced and the merge conflicts
- **THEN** archive SHALL abort with an actionable error, the worktree and `opsx/<change>` branch SHALL be preserved, and the change SHALL NOT be moved to the archive directory

#### Scenario: Cleanup is safe when no worktree exists
- **IF** archive runs for a change that was implemented same-tree by explicit override
- **THEN** the merge-and-remove step SHALL be skipped without error

### Requirement: Validation Gates Manifest Reference

THE schema SHALL define `openspec/opsx-gates.yaml` as the manifest where a project declares validation commands, replacing the previously dangling `project.md` validator reference, and the schema documentation SHALL describe its structure and how opsx gate consumes it. WHILE a change declares Scale M or above, THE gate SHALL require at least one agent-independent validation source (a manifest with one or more `required: true` commands, or a non-empty `OPSX_VALIDATE`); IF none is present THEN opsx gate SHALL fail the gate, UNLESS review.md front-matter sets `validation_source_mode: waived` with a recorded human rationale.

#### Scenario: Manifest documented in schema
- **WHEN** the schema's README and apply instruction are read
- **THEN** they SHALL describe `opsx-gates.yaml` with `gates` entries each having `id`, `run`, and `required`, and SHALL state that opsx gate executes each command by exit code

#### Scenario: Template shipped with the schema
- **WHEN** the schema is deployed
- **THEN** a `templates/opsx-gates.yaml` example SHALL be present in the deployed schema's templates directory

---

### Requirement: Review front-matter carries role models

THE review.md front-matter SHALL optionally carry `author_model` (string), `review_models` (string or list), and `impl_model` (string), plus optional provider keys — a default `provider` (string) and per-role `author_provider` / `review_provider` / `impl_provider` (strings) — giving per-change overrides that the opsx models resolver reads above the project and user config files. Model values MAY be provider-qualified (`<provider>/<id>`); the provider keys qualify bare ids.

#### Scenario: Per-change model override recorded
- **WHEN** review.md front-matter sets `author_model`, `review_models`, or `impl_model`
- **THEN** `opsx models <role> --change <name>` SHALL return those values above the project/user files

#### Scenario: Per-change provider override recorded
- **WHEN** review.md front-matter sets a `provider` default or a per-role `*_provider`
- **THEN** `opsx models <role> --change <name>` SHALL qualify the role's bare model id with that provider (an explicit provider in the value still wins)

#### Scenario: Front-matter model fields are optional
- **IF** the front-matter omits the model fields
- **THEN** the schema SHALL remain valid and the resolver SHALL fall through to the project/user/default layers

