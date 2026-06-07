# opsx-skill-integration Specification

## Purpose
TBD - created by archiving change add-opsx-superpowers-schema. Update Purpose after archive.
## Requirements

### Requirement: Schema-aware openspec-propose

The `openspec-propose` skill at `dot_local/share/agent-harness/canonical/skills/openspec-propose/SKILL.md` SHALL detect when the active change uses `schema: opsx-superpowers` and SHALL adapt its workflow to drive the new artifact graph rather than the default `spec-driven` four-artifact sequence.

#### Scenario: Schema detection at change creation
- **WHEN** the user invokes openspec-propose against a project whose `openspec/config.yaml` declares `schema: opsx-superpowers`
- **THEN** the skill SHALL pass `--schema opsx-superpowers` to `openspec new change` and SHALL follow the artifact graph returned by `openspec status --change <name> --json`

#### Scenario: Up-front Scale prompt
- **WHEN** the skill begins propose flow under `opsx-superpowers`
- **THEN** the skill SHALL ask the user to declare a Scale class (`XS | S | M | L | XL`) before authoring any artifact, and SHALL record the choice in `review.md` once that artifact is reached

#### Scenario: Scale-driven skipping
- **WHEN** Scale is declared `XS` and the user invokes openspec-propose
- **THEN** the skill SHALL skip authoring `specs`, `clarify`, `design`, `adr`, `analyze`, `review`, `plan`, `verify`, and `retrospective`, producing only `proposal.md` and `tasks.md`

#### Scenario: Schema-only fallback when Superpowers absent
- **WHEN** the skill cannot resolve a referenced Superpowers-style capability skill (e.g., `verification-before-completion`)
- **THEN** the skill SHALL log the unavailability and continue using the manual fallback documented in the artifact instruction, writing to the same artifact paths and structure

### Requirement: Clarify-driven openspec-propose

When the active schema is `opsx-superpowers` and Scale ≥ S, the `openspec-propose` skill SHALL invoke the new `dot_local/share/agent-harness/canonical/skills/clarify-spec/` skill against the produced `specs/**/spec.md` files before allowing design generation, and SHALL collect the clarify findings into `clarify.md`.

#### Scenario: Clarify gates design
- **WHEN** the clarify pass produces one or more findings with status `unanswered`
- **THEN** the skill SHALL refuse to generate `design.md` and SHALL prompt the user to resolve each finding using the 2-option questions

#### Scenario: Deferred findings are surfaced
- **WHEN** the user marks one or more clarify findings `deferred`
- **THEN** the skill SHALL proceed to design but SHALL ensure those findings are echoed into `analyze.md`'s outstanding-risks section

### Requirement: Analyze gates tasks generation

The `openspec-propose` skill SHALL run the analyze pass before generating `tasks.md`, and SHALL refuse to produce tasks if any analyze finding is marked `blocker`. For changes with Scale ≥ L, the analyze pass SHALL invoke the `adversarial-review-cycle` skill rather than relying on a single-model self-review.

#### Scenario: Blocker prevents task generation
- **WHEN** `analyze.md` contains at least one finding with severity `blocker`
- **THEN** the skill SHALL halt and SHALL summarize the blockers to the user with proposed remediations

#### Scenario: Scale-L invokes adversarial-review-cycle
- **WHEN** Scale is `L` or `XL`
- **THEN** the analyze step SHALL dispatch through `adversarial-review-cycle` with multiple models per the existing skill's defaults, and SHALL record the round-by-round findings as appendices in `analyze.md`

### Requirement: Mode-driven openspec-apply-change

The `openspec-apply-change` skill at `dot_local/share/agent-harness/canonical/skills/openspec-apply-change/SKILL.md` SHALL read the mode flags from `review.md` at the start of apply and SHALL dispatch its workflow accordingly: file-contract enforcement per task, intent-aware repair-prompt suffixes when validators fail, and worktree-based execution when `Worktree Mode` is `worktree-eligible` or `worktree-required`.

#### Scenario: Pre-flight commit before worktree
- **WHEN** the skill begins apply and `Worktree Mode` is not `same-tree`
- **THEN** the skill SHALL run `git status --porcelain openspec/changes/<name>/`, and if any artifact file under that subtree is unstaged or uncommitted, SHALL stage and commit only that subtree on the integration branch before creating the worktree

#### Scenario: File contracts enforced via subagent wrap-up
- **WHEN** a task declares `files_allowed` or `files_forbidden` and the task executes in a subagent
- **THEN** the subagent's final step SHALL run `git diff --name-only` against those globs and SHALL report any `scope_violation` finding to the main agent before the task is marked complete

#### Scenario: Intent-aware repair prompt
- **WHEN** validators fail during apply and the task declares `intent: fix`
- **THEN** the repair prompt SHALL include a constraints block "CONSTRAINTS: Fix only failing validators. Do NOT refactor unrelated code. Do NOT add new features." and SHALL inject the structured `Issues[]` list

#### Scenario: Refactor intent removes restrictive constraints
- **WHEN** the failing task declares `intent: refactor`
- **THEN** the repair prompt SHALL NOT inject the fix-mode constraints, and SHALL instead include language permitting unrelated cleanup within the task's `files_allowed` scope

### Requirement: Archive HARD-GATE on verify

The `openspec-archive-change` skill at `dot_local/share/agent-harness/canonical/skills/openspec-archive-change/SKILL.md` SHALL refuse to archive a change whose schema is `opsx-superpowers` until `verify.md` exists and contains a Completion Decision marked green. The skill SHALL additionally check AC↔test mapping and offer to promote `retrospective.md` Promote-candidates into long-term memory via `mcp_memory_store_memory`.

#### Scenario: Missing verify blocks archive
- **WHEN** the user attempts to archive a change with `Verification Mode: retained-required` and `verify.md` is absent
- **THEN** the skill SHALL refuse to archive and SHALL prompt the user to run the verify step

#### Scenario: Red verify blocks archive
- **WHEN** `verify.md` exists but its Completion Decision is `red` or `yellow`
- **THEN** the skill SHALL refuse to archive and SHALL list the failing verify checks

#### Scenario: Retrospective promote-candidates ingested
- **WHEN** the change directory contains `retrospective.md` and it has a non-empty `Promote candidates` section
- **THEN** the skill SHALL parse each candidate, classify it as a `decision | learning | convention | implementation | important | context` memory type per the user's memory-server contract, and SHALL prompt the user to confirm or skip each one before calling `mcp_memory_store_memory`

#### Scenario: ADR promotion before archive
- **WHEN** `design.md` contains a Decisions section with ≥1 decision passing the 4-point test
- **THEN** the skill SHALL offer to promote each qualifying decision into `<repo>/adr/ADR-NNNN-<slug>.md` before archive, using the schema's `adr` template

### Requirement: clarify-spec skill exists and is invokable

A new skill SHALL be created at `dot_local/share/agent-harness/canonical/skills/clarify-spec/SKILL.md` that implements the three-pass clarify procedure (ambiguity, inconsistency, completeness). The skill SHALL produce output in the format consumed by the schema's `clarify.md` artifact.

#### Scenario: Skill metadata complete
- **WHEN** the skill is loaded by pi
- **THEN** its frontmatter SHALL include `name: clarify-spec`, `description: <one-line>`, `license`, and `compatibility`; and the skill body SHALL describe the three passes with input and output contracts

#### Scenario: Output structure consumable by clarify.md
- **WHEN** the skill is invoked against a `specs/**/spec.md` file
- **THEN** its output SHALL be a markdown section with numbered findings, each finding written as a 2-option question with status field `unanswered | answered | deferred`

#### Scenario: Skill references its own procedure
- **WHEN** the skill body is read
- **THEN** it SHALL reference `dot_local/share/agent-harness/canonical/skills/clarify-spec/references/three-pass-procedure.md`, `dot_local/share/agent-harness/canonical/skills/clarify-spec/references/ears-patterns.md`, and `dot_local/share/agent-harness/canonical/skills/clarify-spec/references/quality-properties.md` as the canonical procedure definitions

### Requirement: Skills remain backward compatible

All four opsx-* skill edits SHALL preserve behavior for changes whose schema is `spec-driven` (the default). The new behavior SHALL be activated only when the resolved schema name returned by `openspec status --change <name> --json` is `opsx-superpowers`.

#### Scenario: Existing spec-driven projects unaffected
- **WHEN** the user invokes any opsx-* skill on a project whose `openspec/config.yaml` declares `schema: spec-driven`
- **THEN** the skill SHALL follow the default four-artifact workflow (proposal → specs → design → tasks) and SHALL NOT prompt for Scale, run clarify, run analyze, or enforce file contracts

#### Scenario: Mid-change schema cannot be switched
- **WHEN** a change is created under one schema and the user attempts to switch by editing `openspec/config.yaml` mid-change
- **THEN** the skills SHALL detect the schema-name drift via `openspec status --change <name> --json` and SHALL refuse to proceed until the user either reverts the config or reissues the change under the new schema
