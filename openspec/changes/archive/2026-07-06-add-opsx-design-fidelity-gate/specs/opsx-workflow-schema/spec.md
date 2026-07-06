# opsx-workflow-schema (delta)

## ADDED Requirements

### Requirement: Design Fidelity Artifact Template

THE schema SHALL ship a `templates/design-fidelity.md` template for the sealed fidelity verdict: a per-AC verdict table (AC reference, `entailed | not-entailed | not-covered`, evidence), an own-line `**Fidelity:**` overall field (`delivered | violated`), judge-provenance and `**Attested HEAD:**` fields, digest-binding fields for intent.md, design.md, and every delta spec file — sha256 each, one own-line field per file in the exact grammar `**Digest sha256 (<change-dir-relative path>):** <64-hex>` (e.g. `**Digest sha256 (specs/opsx-gate-enforcement/spec.md):** <64-hex>`), so the deterministic gate parser and the template never diverge on field naming, an optional human-waiver field written only by a human ruling at the decision-audit landing, an `Advisory Findings` section recording ambiguity-routed clarify-class findings per AC (advisory outcomes never occupy the three-value verdict column and never affect the gate-read `Fidelity` field), and template comments documenting the bounded judge contract and the full-sweep re-judge rule. Gate-read fields SHALL be own-line `**Field:** value` form with multi-line-only HTML comments (single-line comments break the comment-stripper).

#### Scenario: Template ships the sealed-verdict contract
- **WHEN** the shipped design-fidelity.md template is inspected
- **THEN** it SHALL carry the per-AC verdict table, the `Fidelity` field, judge provenance, `Attested HEAD`, per-file digest-binding fields, the `Advisory Findings` section, and the documented bounded contract + full-sweep re-judge rule

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

### Requirement: Worktree Lifecycle Ownership

THE schema's apply and archive instructions SHALL own the full worktree lifecycle for EVERY change at every Scale — worktree execution is the only execution model: creating an isolated worktree on a branch named `opsx/<change>` before implementation, capturing the base SHA, and merging then removing the worktree at archive only after the gate is green.

#### Scenario: Worktree created before implementation
- **WHEN** apply begins for any change at any Scale
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
- **THEN** apply SHALL abort with an actionable error and SHALL NOT proceed to any implementation task — there is no same-tree fallback

#### Scenario: Budget exhaustion preserves the worktree
- **WHILE** a worktree exists
- **IF** the loop stops because its iteration budget is exhausted
- **THEN** the worktree and its `opsx/<change>` branch SHALL be preserved for inspection and SHALL NOT be removed

#### Scenario: Worktree merged and removed at archive
- **WHEN** archive proceeds for a change
- **THEN** the `opsx/<change>` branch SHALL be landed onto the named integration branch using the configured strategy and the worktree SHALL be removed, and this SHALL occur only after opsx gate reports green

#### Scenario: Post-green merge conflict aborts archive safely
- **WHILE** opsx gate is green
- **IF** landing the branch fails because the integration branch advanced and the merge conflicts
- **THEN** archive SHALL abort with an actionable error, the worktree and `opsx/<change>` branch SHALL be preserved, and the change SHALL NOT be moved to the archive directory

### Requirement: Per-task file contracts

Each task in `tasks.md` SHALL optionally declare `files_allowed`, `files_forbidden`, `allow_new_files`, and `intent` scope contracts. The contract field format SHALL be strict (sub-bullets under the task checkbox at fixed indent; minimatch globs one per line under list-type fields). When a task is implemented in the worktree or by a subagent, the wrap-up step SHALL diff against these contracts using the immutable `Diff Base SHA` recorded at worktree creation and report violations.

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
- **IF** a task declares `intent: fix` and validators fail
- **THEN** the repair prompt SHALL include the constraints block "Fix only failing validators. Do NOT refactor unrelated code. Do NOT add new features. Tests MAY be added when TDD mode is on." along with a structured `Issues[]` list
- **IF** a task declares `intent: refactor` and validators fail
- **THEN** the repair prompt SHALL NOT include the fix-mode constraints and SHALL instead permit unrelated cleanup within the task's `files_allowed` scope

### Requirement: Apply-time writeback and workspace discipline

The `apply.instruction` SHALL enforce three disciplines: pre-flight commit of the change directory before the worktree is created; main-agent-as-writeback-owner for all delegated work; output-redirection that forbids writes to scattered or parallel doc trees (in particular `docs/superpowers/`).

#### Scenario: Pre-flight commit before worktree
- **WHEN** apply begins for any change
- **THEN** the apply step SHALL run `git status --porcelain openspec/changes/<name>/`, and if any artifact files are unstaged or uncommitted, SHALL stage and commit only that subtree on the integration branch before creating the worktree

#### Scenario: Subagent does not own artifact writes
- **WHEN** a task is dispatched to a subagent
- **THEN** the subagent SHALL produce its findings as a structured handoff to the main agent, and SHALL NOT directly edit `tasks.md`, `plan.md`, `verify.md`, or any other artifact under `openspec/changes/<name>/`

#### Scenario: Output redirection prevents parallel doc trees
- **WHEN** apply invokes any Superpowers-style capability hook (brainstorming, writing-plans, etc.)
- **THEN** the invocation SHALL include explicit instructions to write output into the current change's `<artifact>.md`, and SHALL forbid creation of files under `docs/superpowers/specs/` or any other parallel tree
