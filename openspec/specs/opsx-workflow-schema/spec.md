# opsx-workflow-schema Specification

## Purpose
The opsx-superpowers OpenSpec schema itself: the artifact DAG and templates, the review.md mode switchboard, Scale tiers, worktree lifecycle ownership with the immutable Diff Base SHA, and per-task file contracts.
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

The schema SHALL declare a `Scale` mode in `review.md` with the collapsed tier vocabulary `XS | S | M`, plus an optional boolean `full_rigor` front-matter key (default false) that opts a Scale-M change into the ADR-promotion, adversarial-on-analyze, retrospective, and full-independent-review extras formerly implied by the `L`/`XL` labels; the former `L` and `XL` labels map to "M + `full_rigor: true`". Scale-tier gating SHALL be enforced by the opsx-* skills (which artifacts they author per Scale), not by the schema YAML (whose artifact graph is static). A review.md declaring a Scale value outside `XS|S|M`, or a non-boolean `full_rigor`, SHALL fail closed (a validation/gate failure), never silently defaulted to a permissive tier. The schema's documentation SHALL clearly state this division so users do not expect `openspec status` to reflect Scale-driven skips.

#### Scenario: README documents Scale tiers, the flag, and skill enforcement
- **WHEN** the schema's `README.md` is read
- **THEN** it SHALL contain a Scale-tier table for `XS|S|M` mapping each tier to which artifacts the opsx-* skills will author, SHALL document the `full_rigor` flag and the extras it enables (former L/XL behavior), AND SHALL explicitly note that the schema's artifact graph is static (the same for all Scales) with skill-level gating being the actual enforcement mechanism

#### Scenario: XS skill behavior
- **WHEN** the user invokes openspec-propose against a project using `schema: opsx-superpowers` and declares `Scale: XS` (typo / comment / single-line config change)
- **THEN** the openspec-propose skill SHALL author `review.md` (the mode switchboard — NEVER skipped at any Scale, since the gate fails closed without a parseable Scale) plus `proposal.md` and `tasks.md`, AND SHALL log "Scale=XS: skipping specs/clarify/design/analyze/plan" so the user understands the deliberate skip

#### Scenario: M skill behavior
- **WHEN** the user declares `Scale: M` (typical feature)
- **THEN** the openspec-propose skill SHALL author the full 8-artifact graph; `openspec-apply-change` SHALL produce `verify.md` at apply end when `Verification Mode` is `retained-recommended` (default) or `retained-required`; ADR promotion and `retrospective.md` SHALL remain optional

#### Scenario: full_rigor invokes adversarial review and prompts for ADR promotion
- **WHEN** the user declares `Scale: M` with `full_rigor: true` (cross-capability or breaking change, formerly `L`)
- **THEN** the analyze artifact's instruction SHALL invoke the `adversarial-review` capability hook (resolves to `adversarial-review-cycle` skill), AND `openspec-archive-change` SHALL examine every Decision in `design.md` against the 4-point test and prompt to promote qualifying decisions to `<repo>/adr/ADR-NNNN-<slug>.md`

#### Scenario: full_rigor forces retrospective before archive
- **WHEN** the user declares `Scale: M` with `full_rigor: true` (new capability or migration, formerly `XL`)
- **THEN** `openspec-archive-change` SHALL refuse to proceed until `retrospective.md` exists in the change directory with a populated Promote-candidates section (rows MAY be empty if there's nothing to promote, but the section itself MUST be present and explicitly confirmed)

#### Scenario: Unknown Scale or non-boolean full_rigor fails closed
- **IF** review.md declares a Scale value outside `XS|S|M`, or a `full_rigor` value that is not a parseable boolean
- **THEN** the schema/gate SHALL treat it as a failure rather than defaulting to a permissive tier or silently ignoring the flag

#### Scenario: In-flight change still labeled L or XL is relabeled at cutover
- **WHILE** a non-archived change created under the prior 5-tier schema still declares `Scale: L` or `Scale: XL`
- **WHEN** this change lands and the change is next gated
- **THEN** the deterministic gate SHALL fail closed on the now-unknown Scale (a loud failure, never a silent permissive pass), and the schema README's migration note SHALL instruct the author to relabel the in-flight change to `Scale: M` with `full_rigor: true` (the former `L`/`XL` mapping); already-archived changes and their historical review records SHALL NOT be rewritten

### Requirement: Mode switchboard in review.md

The `review.md` artifact SHALL declare a controlled-vocabulary mode switchboard whose values gate apply-time behavior. The required modes SHALL be: `Scale`, `Execution Mode`, `Verification Mode`, `Debug Mode`, `Review Status`, `Delegation Mode`, `Worktree Mode`, `Code Review Mode`, `Loop Max Iterations`, `Spec Level`, and `Doneness Mode`. The default value of `Worktree Mode` SHALL be DERIVED BY TIER: `same-tree` for Scale XS and S, and `worktree-required` for Scale M; an explicit `Worktree Mode` value recorded in review.md SHALL always win over the tier default. THE review.md artifact SHALL additionally carry a machine-readable front-matter block (YAML) at the top of the file mirroring at least `scale`, `full_rigor`, `worktree_mode`, `verification_mode`, `code_review_mode`, `loop_max_iterations`, `validation_source_mode`, and `doneness_mode`, so that opsx gate reads these values from structured fields rather than scraping the prose mode table. THE `doneness_mode` field SHALL take one of `required` or `waived`, defaulting to `required` for Scale M and above, and WHERE it is `waived` a non-empty `doneness_waiver_rationale` front-matter field SHALL be recorded, mirroring `validation_source_mode`.

#### Scenario: Machine-readable front-matter present
- **WHEN** review.md is authored
- **THEN** its leading YAML front-matter SHALL contain `scale`, `full_rigor`, `worktree_mode`, `verification_mode`, `code_review_mode`, `loop_max_iterations`, `validation_source_mode`, and `doneness_mode` fields whose values match the prose mode table

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

#### Scenario: Worktree Mode default derives by tier
- **WHEN** `review.md` is authored without an explicit `Worktree Mode` value
- **THEN** the effective `Worktree Mode` SHALL be `same-tree` for Scale XS and S and `worktree-required` for Scale M, AND an explicit `Worktree Mode` value SHALL always override the tier default

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
- **IF** a task declares `intent: fix` and validators fail
- **THEN** the repair prompt SHALL include the constraints block "Fix only failing validators. Do NOT refactor unrelated code. Do NOT add new features. Tests MAY be added when TDD mode is on." along with a structured `Issues[]` list
- **IF** a task declares `intent: refactor` and validators fail
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

### Requirement: Review Max Rounds Front Matter

THE review.md front-matter MAY carry a `review_max_rounds` field (positive integer) bounding blind gating review rounds per change, and WHEN the field is absent or unparseable consumers SHALL apply the default of 5, and in this change the field SHALL be read by the orchestration skills only — `opsx gate`'s decision logic is unchanged.

#### Scenario: Absent field defaults
- **WHEN** a change's review.md front-matter carries no review_max_rounds
- **THEN** the orchestration SHALL apply a budget of 5 rounds

#### Scenario: Explicit override honored
- **WHEN** review.md front-matter sets review_max_rounds to a positive integer
- **THEN** the orchestration SHALL use that value as the round budget

#### Scenario: Invalid value falls back
- **IF** review_max_rounds is zero, negative, or non-integer
- **THEN** consumers SHALL treat it as absent and apply the default of 5

### Requirement: Convergence Template Support

THE opsx-superpowers schema templates SHALL ship the convergence-discipline surfaces: the review.md template SHALL include a `Scope Expansions` section and the `review_max_rounds` front-matter key (commented or defaulted), the code-review.md template SHALL include the round-ledger fields and the verdict-contract/rubric header, and the schema SHALL ship a `follow-ups.md` template for out-of-scope finding routing, authored at the lifecycle moment the first out-of-scope finding is routed (not a declared always-required artifact, matching the verify/retrospective/doneness pattern).

#### Scenario: Templates carry the sections
- **WHEN** a new change's review.md and code-review.md are authored from the shipped templates
- **THEN** review.md SHALL contain the Scope Expansions section and code-review.md SHALL contain the round-ledger fields and verdict-contract header

#### Scenario: Follow-ups authored on first routing
- **WHEN** the first out-of-scope finding is routed for a change
- **THEN** follow-ups.md SHALL be created from the shipped template in the change directory

#### Scenario: Absent follow-ups does not fail completeness
- **IF** a change routes no out-of-scope findings
- **THEN** the absence of follow-ups.md SHALL NOT fail schema completeness or the gate

---

### Requirement: Loop hold front-matter keys

THE review.md template SHALL document optional `loop_hold` and `loop_hold_reason`
front-matter keys: `loop_hold: true` is an orchestrator-settable landing signal read by
the loop host (NOT by opsx gate — the gate SHALL remain ignorant of hold state), and a
`true` value REQUIRES a non-empty `loop_hold_reason`. The template SHALL state the
clearing rule: only an explicit named re-arm clears a hold; agents never clear it.

#### Scenario: Template documents the hold contract
- **WHEN** review.md is authored from the template
- **THEN** the template SHALL carry commented `loop_hold` / `loop_hold_reason` keys explaining the set-by-orchestrator, cleared-by-named-re-arm-only contract and that the gate does not read them

#### Scenario: Gate ignores hold state
- **WHEN** opsx gate evaluates a change whose review.md carries `loop_hold: true`
- **THEN** gate checks and exit code SHALL be unaffected by the hold fields

### Requirement: Per-Tier Review Stack

THE schema documentation SHALL define a per-tier review stack table keyed on `XS|S|M` and the `full_rigor` flag, stating for each tier which review artifacts and dispatches apply: at Scale M without `full_rigor` clarify open questions live in the proposal's `## Open Questions` (no standalone clarify), analyze is deterministic-checks-only (no blind analyze dispatch), and the doneness verdict rides the blind code-review dispatch while still sealed to a separate `doneness.md`; at Scale M with `full_rigor` the full independent stack (standalone blind clarify, blind analyze dispatch, independently dispatched blind doneness judge) applies. The 2-model blind adversarial code review SHALL remain gating-required at every tier and SHALL NOT be weakened by the table.

#### Scenario: Table documents the plain-M stack
- **WHEN** the schema README's per-tier review-stack table is read
- **THEN** it SHALL show that Scale M without `full_rigor` folds clarify into proposal open questions, runs analyze deterministic-only, and rides doneness on the code-review dispatch (still sealed to a separate `doneness.md`)

#### Scenario: Table documents the full_rigor stack
- **WHEN** the per-tier review-stack table is read for `full_rigor: true`
- **THEN** it SHALL show the full independent stack: standalone blind clarify, blind analyze dispatch, and an independently dispatched blind doneness judge

#### Scenario: Table never weakens the code review
- **WHEN** the per-tier review-stack table is read
- **THEN** it SHALL state that the 2-model blind adversarial code review is gating-required at every tier and is not reduced by the thinning

### Requirement: Path-Scoped Integration Commits

THE schema SHALL state, as a schema-level workflow rule the opsx-* skills embed, that loop-driven commits on the integration checkout SHALL be path-scoped using `git commit -- <paths>` (never a bare `git commit` and never `git add -A`), so a single loop-driven commit touches only its own change's `openspec/changes/<change>/` paths and cannot sweep another concurrent change's working-tree edits into the commit.

#### Scenario: Skills embed the path-scoped commit rule
- **WHEN** a loop-driven skill (propose/apply/archive) makes an integration-checkout commit
- **THEN** it SHALL commit with explicit `-- <paths>` scoping and SHALL NOT use a bare `git commit` or `git add -A`, per the embedded schema rule

#### Scenario: Rule is documented at the schema level
- **WHEN** the schema documentation is read
- **THEN** it SHALL state the path-scoped-commit rule as a workflow discipline the skills must follow, backstopped by the deterministic multi-dir integration-commit detector (opsx-cli)

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

A change MAY declare retired tokens and forbidden patterns in a machine-readable `sweep.txt` file in its change directory — one extended-regex pattern per line, `#`-prefixed comment lines and blank lines ignored — and THE declared patterns SHALL define the migration-completeness sweep for that change over all git-tracked shipped surfaces, WHERE the entire OpenSpec workspace (`openspec/**` — the capability specs plus in-flight and archived change artifacts) and ADR history (`adr/**`) are excluded from the swept surface because none of it is a deployed surface (Constitution VIII) and it legitimately records retired vocabulary (the live capability specs still carry the outgoing tokens until this change archives its deltas into them).

#### Scenario: Declaration format parsed
- **WHEN** a sweep.txt containing patterns, comments, and blank lines is read
- **THEN** only the non-comment, non-blank lines SHALL be treated as patterns

#### Scenario: History surfaces excluded
- **WHEN** the sweep runs
- **THEN** hits inside openspec/** (capability specs plus change artifacts) and adr/** SHALL NOT be reported

#### Scenario: No declaration means no sweep obligation
- **IF** a change directory contains no sweep.txt
- **THEN** the sweep SHALL be a no-op success for that change

### Requirement: Template Mode Table Mirrors Derived Defaults

WHERE the review.md template ships a front-matter mode key commented out so a tier-derived default applies, THE template's human-facing prose table SHALL present that mode's value as derived (naming the derivation), never as a stale literal value that contradicts the derived default.

#### Scenario: Code Review Mode row shows derivation
- **WHEN** the shipped review.md template is read
- **THEN** the Code Review Mode table row SHALL present the value as derived (M ⇒ gating-required, XS/S ⇒ advisory), not the literal `advisory`

### Requirement: Integration Branch Locator Default Detected

THE review.md template's `**Integration Branch:**` locator field SHALL ship the placeholder sentinel `<detected-at-capture>` — the exact token the `opsx-cli` resolver recognizes as not-a-real-value (clarify C1, single source of truth) — never a hardcoded branch literal as the effective default; the sentinel SHALL direct capture-time detection (the `opsx-cli` `Integration Branch Resolution` order, steps without the locator-field step) to fill the value when apply captures the locator, so a repository whose integration branch is not named `main` records its true branch rather than inheriting a wrong literal.

#### Scenario: Template placeholder directs detection
- **WHEN** the review.md template is inspected as shipped
- **THEN** the `**Integration Branch:**` field SHALL carry the `<detected-at-capture>` sentinel (not a bare branch literal presented as the effective value), documenting that apply fills it via the deterministic resolver at capture time

#### Scenario: Capture in a non-main repo records the true branch
- **WHILE** apply captures the Diff Base + Worktree locator in a repository whose integration branch resolves to `trunk`
- **WHEN** the `**Integration Branch:**` field is written
- **THEN** it SHALL record `trunk` (the resolver's result), and downstream integration-branch-dependent checks SHALL read that committed value first

