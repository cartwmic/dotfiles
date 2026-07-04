# opsx-skill-integration Specification

## Purpose
The contracts binding the openspec-* skills to the opsx-superpowers schema branch: schema detection at change creation, mode-flag dispatch during apply, archive hard-gates, and ADR/memory promotion flows.
## Requirements
### Requirement: Schema-aware openspec-propose

The `openspec-propose` skill at `dot_local/share/agent-harness/canonical/skills/openspec-propose/SKILL.md` SHALL detect when the active change uses `schema: opsx-superpowers` and SHALL adapt its workflow to drive the new artifact graph rather than the default `spec-driven` four-artifact sequence.

#### Scenario: Schema detection at change creation
- **WHEN** the user invokes openspec-propose against a project whose `openspec/config.yaml` declares `schema: opsx-superpowers`
- **THEN** the skill SHALL pass `--schema opsx-superpowers` to `openspec new change` and SHALL follow the artifact graph returned by `openspec status --change <name> --json`

#### Scenario: Up-front Scale prompt
- **WHEN** the skill begins propose flow under `opsx-superpowers`
- **THEN** the skill SHALL ask the user to declare a Scale class from the collapsed vocabulary (`XS | S | M`) — and, for a former-`L`/`XL` change, whether to set the boolean `full_rigor` flag (which maps the former `L`/`XL` extras onto `M`) — before authoring any artifact, and SHALL record the choice in `review.md` once that artifact is reached; it SHALL NOT offer `L` or `XL` as declarable Scale values, since the deterministic gate fails closed on any Scale outside `XS | S | M`

#### Scenario: Scale-driven skipping
- **WHEN** Scale is declared `XS` and the user invokes openspec-propose
- **THEN** the skill SHALL skip authoring `specs`, `clarify`, `design`, `adr`, `analyze`, `plan`, `verify`, and `retrospective`, producing `review.md` (the mode switchboard — never skipped at any Scale) plus `proposal.md` and `tasks.md`

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

The `openspec-propose` skill SHALL run the analyze pass before generating `tasks.md`, and SHALL refuse to produce tasks if any analyze finding is marked `blocker`. For changes carrying `full_rigor: true` (the former Scale ≥ `L` behavior), the analyze pass SHALL invoke the `adversarial-review-cycle` skill rather than relying on a single-model self-review; at plain Scale `M` without `full_rigor` the analyze pass is thinned to its deterministic checks (no separate blind analyze dispatch), per the opsx-adversarial-review M-Tier Review Stack Thinning requirement.

#### Scenario: Blocker prevents task generation
- **WHEN** `analyze.md` contains at least one finding with severity `blocker`
- **THEN** the skill SHALL halt and SHALL summarize the blockers to the user with proposed remediations

#### Scenario: Full-rigor invokes adversarial-review-cycle
- **WHEN** review.md front-matter sets `full_rigor: true` (a former `L`/`XL` change)
- **THEN** the analyze step SHALL dispatch through `adversarial-review-cycle` with multiple models per the existing skill's defaults, and SHALL record the round-by-round findings as appendices in `analyze.md`

#### Scenario: Plain M thins analyze to deterministic checks
- **WHEN** the change is Scale `M` and review.md front-matter does NOT set `full_rigor: true`
- **THEN** the analyze pass SHALL run only its deterministic checks with NO separate blind analyze dispatch, matching the opsx-adversarial-review thinning, and the 2-model blind adversarial code review SHALL remain gating-required and unweakened

### Requirement: Mode-driven openspec-apply-change

The `openspec-apply-change` skill at `dot_local/share/agent-harness/canonical/skills/openspec-apply-change/SKILL.md` SHALL read the mode flags from `review.md` at the start of apply and SHALL dispatch its workflow accordingly: file-contract enforcement per task, intent-aware repair-prompt suffixes when validators fail, and worktree-based execution when `Worktree Mode` is `worktree-eligible` or `worktree-required`.

#### Scenario: Pre-flight commit before worktree
- **WHEN** the skill begins apply and `Worktree Mode` is not `same-tree`
- **THEN** the skill SHALL run `git status --porcelain openspec/changes/<name>/`, and if any artifact file under that subtree is unstaged or uncommitted, SHALL stage and commit only that subtree on the integration branch before creating the worktree

#### Scenario: File contracts enforced via subagent wrap-up
- **WHEN** a task declares `files_allowed` or `files_forbidden` and the task executes in a subagent
- **THEN** the subagent's final step SHALL run `git diff --name-only` against those globs and SHALL report any `scope_violation` finding to the main agent before the task is marked complete

#### Scenario: Intent-aware repair prompt
- **IF** validators fail during apply and the task declares `intent: fix`
- **THEN** the repair prompt SHALL include a constraints block "CONSTRAINTS: Fix only failing validators. Do NOT refactor unrelated code. Do NOT add new features." and SHALL inject the structured `Issues[]` list

#### Scenario: Refactor intent removes restrictive constraints
- **WHEN** the failing task declares `intent: refactor`
- **THEN** the repair prompt SHALL NOT inject the fix-mode constraints, and SHALL instead include language permitting unrelated cleanup within the task's `files_allowed` scope

### Requirement: Archive HARD-GATE on verify

The `openspec-archive-change` skill at `dot_local/share/agent-harness/canonical/skills/openspec-archive-change/SKILL.md` SHALL refuse to archive a change whose schema is `opsx-superpowers` until `verify.md` exists and contains a Completion Decision marked green. The skill SHALL additionally check AC↔test mapping and offer to promote `retrospective.md` Promote-candidates into long-term memory via the hindsight `retain` tool.

#### Scenario: Missing verify blocks archive
- **WHEN** the user attempts to archive a change with `Verification Mode: retained-required` and `verify.md` is absent
- **THEN** the skill SHALL refuse to archive and SHALL prompt the user to run the verify step

#### Scenario: Red verify blocks archive
- **WHEN** `verify.md` exists but its Completion Decision is not `green` (the verdict vocabulary is binary green/red; no other value is valid)
- **THEN** the skill SHALL refuse to archive and SHALL list the failing verify checks

#### Scenario: Retrospective promote-candidates ingested
- **WHEN** the change directory contains `retrospective.md` and it has a non-empty `Promote candidates` section
- **THEN** the skill SHALL parse each candidate (content + `project:`/`topic:` tags; NO memory-type classification — the hindsight backend has no type taxonomy) and SHALL prompt the user to confirm or skip each one before calling the hindsight `retain` tool

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

### Requirement: openspec-loop orchestrator skill exists

A new skill SHALL be created at `dot_local/share/agent-harness/canonical/skills/openspec-loop/SKILL.md` implementing the single-orchestrator loop that advances an opsx-superpowers change until opsx gate is green, delegating review steps to subagents per the consolidated `opsx-loop` capability (which absorbs the retired `opsx-loop-orchestration` capability under B3).

#### Scenario: Skill metadata complete
- **WHEN** the skill is loaded by a harness
- **THEN** its frontmatter SHALL include `name: openspec-loop`, a one-line `description`, `license`, and `compatibility`, and the body SHALL describe the gate-driven cycle and the subagent-review-against-baseline rule

#### Scenario: Skill deploys cross-harness
- **WHEN** `chezmoi apply` runs followed by the harness-config apply step
- **THEN** the skill SHALL be symlinked into every harness skills directory as `openspec-loop`, consistent with the canonical-skill deployment pattern

#### Scenario: Kickoff adapter carries no workflow logic
- **WHEN** a harness-specific kickoff (such as a pi extension command) invokes the loop
- **THEN** that adapter SHALL only wire the worker to the openspec-loop skill and the judge to opsx gate, and removing the adapter SHALL NOT remove any workflow logic

### Requirement: openspec-explore freezes intent

The `openspec-explore` skill SHALL, on conclusion of an explore session for an opsx-superpowers change, write the agreed intent, constraints, and invariants to `intent.md` in the change directory so the loop and review subagents can treat it as the baseline.

#### Scenario: Intent written on explore conclusion
- **WHEN** an explore session concludes with user-confirmed intent under schema opsx-superpowers
- **THEN** `intent.md` SHALL be written to the change directory containing intent, constraints, and invariants

#### Scenario: Spec-driven projects unaffected
- **WHEN** explore concludes for a project whose schema is `spec-driven`
- **THEN** no `intent.md` SHALL be required and the skill SHALL behave as before this change

---

### Requirement: Skills honor configured role models

The openspec-loop, openspec-propose, and openspec-apply-change skills SHALL consult the resolved role models when authoring artifacts (author role) and dispatching review subagents (review role) and implementation subagents (impl role), and SHALL fall back to the session model when a role is unset.

#### Scenario: Review subagents use the review models
- **WHEN** a skill dispatches blind review subagents and `review` models are configured (via opsx models / `OPSX_REVIEW_MODELS`)
- **THEN** it SHALL dispatch one reviewer per configured review model

#### Scenario: Implementation subagents use the impl model
- **WHEN** a skill dispatches an implementation subagent and an `impl` model is configured
- **THEN** that subagent SHALL be dispatched with the configured impl model

#### Scenario: Dispatch honors the resolved provider
- **WHEN** a skill dispatches a review or impl subagent and the resolved value is provider-qualified (`<provider>/<id>`)
- **THEN** the dispatch SHALL pass the provider-qualified value so the subagent runs on the configured provider

#### Scenario: Authoring stays in-session regardless of author model
- **WHILE** `author_in_session` is true or unset
- **WHEN** a skill authors artifacts (even if an `author` model is configured)
- **THEN** it SHALL author in the parent session and SHALL NOT dispatch an authoring subagent; `author_model` is consumed ONLY for delegated authoring when `author_in_session` is false

#### Scenario: Unset roles preserve current behavior
- **IF** a role is unset at every layer
- **THEN** the skill SHALL use the session/default model exactly as before this change

