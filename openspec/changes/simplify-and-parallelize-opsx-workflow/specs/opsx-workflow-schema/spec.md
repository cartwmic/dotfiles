<!-- authored: delegate spec-consolidation -->
# Capability: opsx-workflow-schema

Delta for simplify-and-parallelize-opsx-workflow: collapse the Scale vocabulary to `XS|S|M`
with an optional `full_rigor` boolean front-matter key (B2); derive the `worktree_mode`
default by tier — XS/S same-tree, M worktree-required, explicit value always wins (B4);
document the per-tier review stack (B1); and embed the path-scoped-commit workflow rule
(A2). Modified requirements restate their full content per the MODIFIED-delta rule.

## MODIFIED Requirements

### Requirement: Scale-adaptive gating (skill-enforced, not schema-enforced)

The schema SHALL declare a `Scale` mode in `review.md` with the collapsed tier vocabulary `XS | S | M`, plus an optional boolean `full_rigor` front-matter key (default false) that opts a Scale-M change into the ADR-promotion, adversarial-on-analyze, retrospective, and full-independent-review extras formerly implied by the `L`/`XL` labels; the former `L` and `XL` labels map to "M + `full_rigor: true`". Scale-tier gating SHALL be enforced by the opsx-* skills (which artifacts they author per Scale), not by the schema YAML (whose artifact graph is static). A review.md declaring a Scale value outside `XS|S|M`, or a non-boolean `full_rigor`, SHALL fail closed (a validation/gate failure), never silently defaulted to a permissive tier. The schema's documentation SHALL clearly state this division so users do not expect `openspec status` to reflect Scale-driven skips.

#### Scenario: README documents Scale tiers, the flag, and skill enforcement
- **WHEN** the schema's `README.md` is read
- **THEN** it SHALL contain a Scale-tier table for `XS|S|M` mapping each tier to which artifacts the opsx-* skills will author, SHALL document the `full_rigor` flag and the extras it enables (former L/XL behavior), AND SHALL explicitly note that the schema's artifact graph is static (the same for all Scales) with skill-level gating being the actual enforcement mechanism

#### Scenario: XS skill behavior
- **WHEN** the user invokes openspec-propose against a project using `schema: opsx-superpowers` and declares `Scale: XS` (typo / comment / single-line config change)
- **THEN** the openspec-propose skill SHALL author only `proposal.md` and `tasks.md`, AND SHALL log "Scale=XS: skipping specs/clarify/design/analyze/review/plan" so the user understands the deliberate skip

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

## ADDED Requirements

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
