# opsx-workflow-schema Specification

## Purpose
TBD - created by archiving change add-opsx-superpowers-schema. Update Purpose after archive.
## Requirements
### Requirement: Schema persistence in chezmoi

The `opsx-superpowers` workflow schema SHALL be persisted canonically in the chezmoi source tree under `dot_local/share/openspec/schemas/opsx-superpowers/` such that running `chezmoi apply` deploys the schema to the user's XDG_DATA_HOME-compliant location `~/.local/share/openspec/schemas/opsx-superpowers/`, where OpenSpec's `getGlobalDataDir()` resolver locates user-override schemas.

#### Scenario: Fresh apply on a new host
- **WHEN** a user clones the chezmoi repository onto a new machine and runs `chezmoi apply`
- **THEN** the directory `~/.local/share/openspec/schemas/opsx-superpowers/` exists and contains `schema.yaml` plus the full `templates/` directory

#### Scenario: Schema resolves at user level
- **WHEN** the user runs `openspec schema which opsx-superpowers` from any project that has no project-local copy
- **THEN** the resolved path SHALL match `${XDG_DATA_HOME:-~/.local/share}/openspec/schemas/opsx-superpowers` (the user-override location) and `openspec schemas` SHALL display the schema with the `(user override)` marker

#### Scenario: Default schema unaffected
- **WHEN** the user runs `openspec schemas` after deploying this change
- **THEN** both `spec-driven` (the OpenSpec default) and `opsx-superpowers` SHALL be listed, and projects whose `openspec/config.yaml` declares `schema: spec-driven` SHALL continue to use the default artifact graph with no change in behavior

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

### Requirement: Scale-adaptive gating (skill-enforced, not schema-enforced)

The schema SHALL declare a `Scale` mode in `review.md` with values `XS | S | M | L | XL`. Scale-tier gating SHALL be enforced by the opsx-* skills (which artifacts they author per Scale), not by the schema YAML (whose artifact graph is static). The schema's documentation SHALL clearly state this division so users do not expect `openspec status` to reflect Scale-driven skips.

#### Scenario: README documents Scale tiers and skill enforcement
- **WHEN** the schema's `README.md` is read
- **THEN** it SHALL contain a Scale-tier table mapping each tier to which artifacts the opsx-* skills will author, AND SHALL explicitly note that the schema's artifact graph is static (the same for all Scales) with skill-level gating being the actual enforcement mechanism

#### Scenario: XS skill behavior
- **WHEN** the user invokes openspec-propose against a project using `schema: opsx-superpowers` and declares `Scale: XS` (typo / comment / single-line config change)
- **THEN** the openspec-propose skill SHALL author only `proposal.md` and `tasks.md`, AND SHALL log "Scale=XS: skipping specs/clarify/design/analyze/review/plan" so the user understands the deliberate skip

#### Scenario: M skill behavior
- **WHEN** the user declares `Scale: M` (typical feature)
- **THEN** the openspec-propose skill SHALL author the full 8-artifact graph; `openspec-apply-change` SHALL produce `verify.md` at apply end when `Verification Mode` is `retained-recommended` (default) or `retained-required`; ADR promotion and `retrospective.md` SHALL remain optional

#### Scenario: L invokes adversarial review and prompts for ADR promotion
- **WHEN** the user declares `Scale: L` (cross-capability or breaking change)
- **THEN** the analyze artifact's instruction SHALL invoke the `adversarial-review` capability hook (resolves to `adversarial-review-cycle` skill), AND `openspec-archive-change` SHALL examine every Decision in `design.md` against the 4-point test and prompt to promote qualifying decisions to `<repo>/adr/ADR-NNNN-<slug>.md`

#### Scenario: XL forces retrospective before archive
- **WHEN** the user declares `Scale: XL` (new capability or migration)
- **THEN** `openspec-archive-change` SHALL refuse to proceed until `retrospective.md` exists in the change directory with a populated Promote-candidates section (rows MAY be empty if there's nothing to promote, but the section itself MUST be present and explicitly confirmed)

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

### Requirement: Apply-time writeback and workspace discipline

The `apply.instruction` SHALL enforce three disciplines: pre-flight commit of the change directory before any worktree is created; main-agent-as-writeback-owner for all delegated work; output-redirection that forbids writes to scattered or parallel doc trees (in particular `docs/superpowers/`).

#### Scenario: Pre-flight commit before worktree
- **WHEN** apply begins and `Worktree Mode` is `worktree-eligible` or `worktree-required`
- **THEN** the apply step SHALL run `git status --porcelain openspec/changes/<name>/`, and if any artifact files are unstaged or uncommitted, SHALL stage and commit only that subtree on the integration branch before creating the worktree

#### Scenario: Subagent does not own artifact writes
- **WHEN** a task is dispatched to a subagent
- **THEN** the subagent SHALL produce its findings as a structured handoff to the main agent, and SHALL NOT directly edit `tasks.md`, `plan.md`, `verify.md`, or any other artifact under `openspec/changes/<name>/`

#### Scenario: Output redirection prevents parallel doc trees
- **WHEN** apply invokes any Superpowers-style capability hook (brainstorming, writing-plans, etc.)
- **THEN** the invocation SHALL include explicit instructions to write output into the current change's `<artifact>.md`, and SHALL forbid creation of files under `docs/superpowers/specs/` or any other parallel tree

### Requirement: Schema-only graceful degradation

The schema's artifacts and apply rules SHALL remain valid and executable when Superpowers-style or other optional capability skills are absent. Invocations of optional skills SHALL be advisory; failure to invoke SHALL fall back to documented manual procedures using the same artifact paths and structure.

#### Scenario: Missing optional skill
- **WHEN** an artifact's instruction prefers an optional skill (e.g., `verification-before-completion`) and that skill is not registered on the host
- **THEN** the apply step SHALL log the unavailability, follow the documented manual fallback procedure in the artifact instruction, and continue without raising an error

#### Scenario: All optional skills missing
- **WHEN** none of the preferred Superpowers-style skills is available
- **THEN** the schema SHALL still produce every required artifact for the declared Scale, and `openspec validate <change> --strict` SHALL pass

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

### Requirement: Author-in-session front-matter flag

THE review.md front-matter SHALL optionally carry `author_in_session` (boolean, default true). WHILE it is true or unset, artifact authoring SHALL remain in the parent session and SHALL NOT be delegated to an authoring subagent.

#### Scenario: Default keeps authoring in-session
- **IF** `author_in_session` is unset
- **THEN** the effective value SHALL be true and authoring SHALL NOT be delegated

#### Scenario: Explicit opt-out permits delegation
- **WHILE** `author_in_session` is false
- **WHEN** authoring runs
- **THEN** authoring MAY be delegated to a subagent dispatched with the configured author model

