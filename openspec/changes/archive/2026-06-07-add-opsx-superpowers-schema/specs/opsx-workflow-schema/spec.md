## ADDED Requirements

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

The `opsx-superpowers` schema SHALL declare an 8-artifact graph in dependency order: `proposal` → `specs` → `clarify` → `design` → `analyze` → `review` → `tasks` → `plan`, with an `apply` block that consumes `tasks` (the full graph reachable transitively). The schema SHALL NOT declare `verify`, `retrospective`, or `adr` as artifacts because OpenSpec's `isComplete` is existence-only and would perpetually report incompleteness for optional artifacts; instead the schema SHALL ship templates for these three so the opsx-* skills can author them at the appropriate lifecycle moment (apply end for verify, pre-archive for retrospective, archive prompt for ADR promotion).

#### Scenario: Validating the schema
- **WHEN** the user runs `openspec schema validate opsx-superpowers`
- **THEN** validation SHALL pass and the artifact list SHALL include exactly `proposal`, `specs`, `clarify`, `design`, `analyze`, `review`, `tasks`, `plan` (8 artifacts)

#### Scenario: Apply block conforms to OpenSpec types
- **WHEN** the schema's `apply` block is inspected
- **THEN** `apply.requires` SHALL be the array `[tasks]` (the full graph is reachable transitively via `tasks.requires → review → analyze → design → clarify → specs → proposal`); `apply.tracks` SHALL be the single string `tasks.md` (the OpenSpec `ApplyPhaseSchema` zod type requires `tracks: string | null`, never an array)

#### Scenario: ADR + verify + retrospective templates exist for skill use
- **WHEN** a project uses `schema: opsx-superpowers`
- **THEN** the templates `adr.md`, `verify.md`, and `retrospective.md` SHALL be present in the deployed schema's `templates/` directory, AND the schema's `apply.instruction` SHALL document the skill contract for each (who produces them, when, and what enforcement they drive)

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

The `review.md` artifact SHALL declare a controlled-vocabulary mode switchboard whose values gate apply-time behavior. The required modes SHALL be: `Scale`, `Execution Mode`, `Verification Mode`, `Debug Mode`, `Review Status`, `Delegation Mode`, `Worktree Mode`, and `Spec Level`.

#### Scenario: Verification Mode gates verify.md retention
- **WHEN** `review.md` declares `Verification Mode: retained-required`
- **THEN** `verify.md` SHALL be a required artifact for apply completion, and `openspec-archive-change` SHALL refuse to proceed unless `verify.md` exists and its Completion Decision is green

#### Scenario: Debug Mode gates systematic-debugging sections
- **WHEN** `review.md` declares `Debug Mode: systematic-debugging`
- **THEN** `plan.md` SHALL contain `Observed Failure` and `Debugging Trail` sections, and these SHALL be populated before any code-modifying task is started

#### Scenario: Delegation Mode dispatches to pi-subagents
- **WHEN** `review.md` declares `Delegation Mode: subagent-required` or `subagent-eligible`
- **THEN** the `openspec-apply-change` skill SHALL dispatch each implementation task through the pi-subagents extension rather than executing inline

#### Scenario: Worktree Mode forces isolation
- **WHEN** `review.md` declares `Worktree Mode: worktree-required`
- **THEN** every implementation task SHALL execute inside an isolated `git worktree`, AND the main agent (not the subagent) SHALL own writeback of artifact files to the change directory, AND the apply skill SHALL capture `git -C <worktree-path> rev-parse HEAD` into `review.md`'s `Worktree Base SHA` field at apply start so subsequent file-contract diffs (`git diff --name-only <base-sha>..HEAD`) remain stable across per-task commits

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

Each task in `tasks.md` SHALL optionally declare `files_allowed`, `files_forbidden`, `allow_new_files`, and `intent` scope contracts. The contract field format SHALL be strict (sub-bullets under the task checkbox at fixed indent; minimatch globs one per line under list-type fields). When a task is implemented in a worktree or by a subagent, the wrap-up step SHALL diff the worktree against these contracts using the Worktree Base SHA captured at apply start and report violations.

#### Scenario: Allowed-glob enforcement with stable diff base
- **WHEN** a task declares `files_allowed: [src/foo/**.ts, tests/foo/**.ts]` and the diff `git diff --name-only <worktree-base-sha>..HEAD` shows a touched file at `src/bar/baz.ts`
- **THEN** the wrap-up step SHALL report a `scope_violation` finding citing the offending path and the contract, AND the task SHALL NOT be marked complete in `tasks.md` until the violation is resolved or the contract is amended; the diff base SHALL remain the captured Worktree Base SHA (not `HEAD`) so commits made earlier in the apply session still appear in the diff

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
