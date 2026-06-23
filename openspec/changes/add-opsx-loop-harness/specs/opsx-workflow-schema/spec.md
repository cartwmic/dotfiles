# Capability: opsx-workflow-schema

## MODIFIED Requirements

### Requirement: Mode switchboard in review.md

The `review.md` artifact SHALL declare a controlled-vocabulary mode switchboard whose values gate apply-time behavior. The required modes SHALL be: `Scale`, `Execution Mode`, `Verification Mode`, `Debug Mode`, `Review Status`, `Delegation Mode`, `Worktree Mode`, `Code Review Mode`, `Loop Max Iterations`, and `Spec Level`. The default value of `Worktree Mode` SHALL be `worktree-required` for all Scales. THE review.md artifact SHALL additionally carry a machine-readable front-matter block (YAML) at the top of the file mirroring at least `scale`, `worktree_mode`, `verification_mode`, `code_review_mode`, `loop_max_iterations`, and `validation_source_mode`, so that opsx-gate reads these values from structured fields rather than scraping the prose mode table.

#### Scenario: Machine-readable front-matter present
- **WHEN** review.md is authored
- **THEN** its leading YAML front-matter SHALL contain `scale`, `worktree_mode`, `verification_mode`, `code_review_mode`, and `loop_max_iterations` fields whose values match the prose mode table

#### Scenario: Front-matter is the sole machine source
- **WHEN** opsx-gate reads review.md
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

### Requirement: Per-task file contracts

Each task in `tasks.md` SHALL optionally declare `files_allowed`, `files_forbidden`, `allow_new_files`, and `intent` scope contracts. The contract field format SHALL be strict (sub-bullets under the task checkbox at fixed indent; minimatch globs one per line under list-type fields). When a task is implemented in a worktree or by a subagent, the wrap-up step SHALL diff against these contracts using the immutable `Diff Base SHA` recorded at worktree creation (or, in same-tree mode, the same-tree `Diff Base SHA`) and report violations.

#### Scenario: Allowed-glob enforcement with stable diff base
- **WHEN** a task declares `files_allowed: [src/foo/**.ts, tests/foo/**.ts]` and the diff `git diff --name-only <Diff Base SHA>..HEAD` shows a touched file at `src/bar/baz.ts`
- **THEN** the wrap-up step SHALL report a `scope_violation` finding citing the offending path and the contract, AND the task SHALL NOT be marked complete until resolved or the contract is amended; the diff base SHALL remain the immutable `Diff Base SHA` (not `HEAD`) so commits made earlier in the apply session still appear in the diff

#### Scenario: Forbidden-glob enforcement
- **WHEN** a task declares `files_forbidden: ["**/*.bak", "**/secrets/**"]` and the diff touches any file matching either glob
- **THEN** the wrap-up step SHALL report a `scope_violation` finding and block task completion

#### Scenario: New-file gating
- **WHEN** a task declares `allow_new_files: false` and the diff contains any newly-created file
- **THEN** the wrap-up step SHALL report a `scope_violation` finding and block task completion

#### Scenario: TDD exemption for test files
- **WHEN** a task declares `allow_new_files: false` AND the apply session's `Execution Mode` is `tdd-required` AND the diff contains a newly-created file matching `tests/**/*`
- **THEN** the wrap-up step SHALL NOT report a `scope_violation` for that file (TDD's first step requires writing a new failing test; this exemption resolves the otherwise-unsatisfiable combination)

#### Scenario: Intent shapes the repair prompt
- **WHEN** a task declares `intent: fix` and validators fail
- **THEN** the repair prompt SHALL include the constraints block "Fix only failing validators. Do NOT refactor unrelated code. Do NOT add new features. Tests MAY be added when TDD mode is on." along with a structured `Issues[]` list
- **WHEN** a task declares `intent: refactor` and validators fail
- **THEN** the repair prompt SHALL NOT include the fix-mode constraints and SHALL instead permit unrelated cleanup within the task's `files_allowed` scope

## ADDED Requirements

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
- **THEN** apply SHALL record `Diff Base SHA` as the current repo HEAD before the first implementation task, leave `Worktree Path` empty, and opsx-gate's freshness locator SHALL resolve the implementation HEAD as the current repo HEAD (no `opsx/<change>` branch required)

#### Scenario: Worktree merged and removed at archive
- **WHEN** archive proceeds for a change implemented in a worktree
- **THEN** the `opsx/<change>` branch SHALL be landed onto the named integration branch using the configured strategy and the worktree SHALL be removed, and this SHALL occur only after opsx-gate reports green

#### Scenario: Post-green merge conflict aborts archive safely
- **WHILE** opsx-gate is green
- **IF** landing the branch fails because the integration branch advanced and the merge conflicts
- **THEN** archive SHALL abort with an actionable error, the worktree and `opsx/<change>` branch SHALL be preserved, and the change SHALL NOT be moved to the archive directory

#### Scenario: Cleanup is safe when no worktree exists
- **IF** archive runs for a change that was implemented same-tree by explicit override
- **THEN** the merge-and-remove step SHALL be skipped without error

### Requirement: Validation Gates Manifest Reference

THE schema SHALL define `openspec/opsx-gates.yaml` as the manifest where a project declares validation commands, replacing the previously dangling `project.md` validator reference, and the schema documentation SHALL describe its structure and how opsx-gate consumes it. WHILE a change declares Scale M or above, THE gate SHALL require at least one agent-independent validation source (a manifest with one or more `required: true` commands, or a non-empty `OPSX_VALIDATE`); IF none is present THEN opsx-gate SHALL fail the gate, UNLESS review.md front-matter sets `validation_source_mode: waived` with a recorded human rationale.

#### Scenario: Manifest documented in schema
- **WHEN** the schema's README and apply instruction are read
- **THEN** they SHALL describe `opsx-gates.yaml` with `gates` entries each having `id`, `run`, and `required`, and SHALL state that opsx-gate executes each command by exit code

#### Scenario: Template shipped with the schema
- **WHEN** the schema is deployed
- **THEN** a `templates/opsx-gates.yaml` example SHALL be present in the deployed schema's templates directory

---

## Acceptance criterion quality checklist

| AC ID | Testable | Solution-free | Unambiguous | Consistent | Complete |
|---|---|---|---|---|---|
| opsx-workflow-schema.mode-switchboard-in-review-md | [x] | [x] | [x] | [x] | [x] |
| opsx-workflow-schema.worktree-lifecycle-ownership | [x] | [x] | [x] | [x] | [x] |
| opsx-workflow-schema.validation-gates-manifest-reference | [x] | [x] | [x] | [x] | [x] |
