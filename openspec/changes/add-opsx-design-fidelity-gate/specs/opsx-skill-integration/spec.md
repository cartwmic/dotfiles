# opsx-skill-integration (delta)

## ADDED Requirements

### Requirement: Worktree Always Skill Discipline

THE opsx-superpowers skill surfaces (openspec-loop, openspec-propose, openspec-apply-change, openspec-archive-change references, openspec-explore) SHALL present worktree execution as the only execution model at every Scale: no skill prose SHALL offer, derive, or describe a same-tree execution path for opsx-superpowers changes; apply SHALL create/reuse the worktree via `opsx worktree ensure` before any implementation task at every Scale including XS; and orchestrator bookkeeping (loop_hold, follow-ups.md routing, Execution Notes) SHALL land on the integration checkout per the writeback-owner discipline so sealed worktree-bound verdicts stay fresh. Placement is not enforced by prose alone: a bookkeeping commit misplaced onto the `opsx/<change>` worktree branch moves the verdict-bound HEAD and therefore STALES the sealed verdicts via the existing range-freshness check — a loud fail-closed gate red whose remedy is re-review — so a placement violation is always detected, never silently green.

#### Scenario: Misplaced bookkeeping commit is detected fail-closed
- **WHILE** code-review.md is sealed at the worktree branch HEAD
- **IF** an orchestrator mistakenly commits a follow-ups.md entry on the worktree branch instead of the integration checkout
- **THEN** the recorded reviewed range no longer matches the recomputed range, the gate SHALL report the verdict stale (fail-closed), and the remedy is re-review — the misplacement cannot produce a silently green gate

#### Scenario: XS change runs the full worktree lifecycle
- **WHEN** an XS change is applied
- **THEN** the skill SHALL run ensure → locator capture → apply → review → merge → cleanup in an isolated worktree, identical in shape to an M change

#### Scenario: No same-tree guidance survives on skill surfaces
- **WHEN** the canonical opsx-superpowers skill surfaces are inspected
- **THEN** no surface SHALL instruct or permit executing a change's implementation directly in the integration checkout

## MODIFIED Requirements

### Requirement: Mode-driven openspec-apply-change

The `openspec-apply-change` skill at `dot_local/share/agent-harness/canonical/skills/openspec-apply-change/SKILL.md` SHALL read the mode flags from `review.md` at the start of apply and SHALL dispatch its workflow accordingly: file-contract enforcement per task, intent-aware repair-prompt suffixes when validators fail, and worktree-based execution unconditionally — worktree is the only execution model, so no mode value enables or disables it.

#### Scenario: Pre-flight commit before worktree
- **WHEN** the skill begins apply for any change
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

### Requirement: Analyze gates tasks generation

The `openspec-propose` skill SHALL run the analyze pass before generating `tasks.md`, and SHALL refuse to produce tasks if any analyze finding is marked `blocker`. For changes carrying `full_rigor: true` (the former Scale ≥ `L` behavior), the analyze pass SHALL invoke the `adversarial-review-cycle` skill rather than relying on a single-model self-review; at plain Scale `M` without `full_rigor` the analyze pass is thinned to its deterministic checks (no separate blind analyze dispatch), per the opsx-adversarial-review M-Tier Review Stack Thinning requirement. WHERE the change carries a `design.md`, tasks generation SHALL additionally be gated on a sealed `design-fidelity.md` verdict of `delivered` (or a human waiver recorded at the decision-audit landing): a `violated`, stale, or absent fidelity verdict SHALL halt tasks generation with the fidelity findings summarized, applying the same halt semantics as an analyze blocker.

#### Scenario: Blocker prevents task generation
- **WHEN** `analyze.md` contains at least one finding with severity `blocker`
- **THEN** the skill SHALL halt and SHALL summarize the blockers to the user with proposed remediations

#### Scenario: Full-rigor invokes adversarial-review-cycle
- **WHEN** review.md front-matter sets `full_rigor: true` (a former `L`/`XL` change)
- **THEN** the analyze step SHALL dispatch through `adversarial-review-cycle` with multiple models per the existing skill's defaults, and SHALL record the round-by-round findings as appendices in `analyze.md`

#### Scenario: Plain M thins analyze to deterministic checks
- **WHEN** the change is Scale `M` and review.md front-matter does NOT set `full_rigor: true`
- **THEN** the analyze pass SHALL run only its deterministic checks with NO separate blind analyze dispatch, matching the opsx-adversarial-review thinning, and the 2-model blind adversarial code review SHALL remain gating-required and unweakened

#### Scenario: Fidelity verdict gates tasks on design-bearing changes
- **WHILE** the change carries design.md
- **IF** design-fidelity.md is absent, stale, or records `Fidelity: violated` with no human waiver
- **THEN** the skill SHALL NOT generate tasks.md, and SHALL summarize the failing fidelity rows with proposed design remediations
