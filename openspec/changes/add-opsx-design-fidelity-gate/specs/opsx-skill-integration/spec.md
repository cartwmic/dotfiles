# opsx-skill-integration (delta)

## ADDED Requirements

### Requirement: Worktree Always Skill Discipline

THE opsx-superpowers skill surfaces (openspec-loop, openspec-propose, openspec-apply-change, openspec-archive-change references, openspec-explore) SHALL present worktree execution as the only execution model at every Scale: no skill prose SHALL offer, derive, or describe a same-tree execution path for opsx-superpowers changes; apply SHALL create/reuse the worktree via `opsx worktree ensure` before any implementation task at every Scale including XS; and orchestrator bookkeeping (loop_hold, follow-ups.md routing, Execution Notes) SHALL land on the integration checkout per the writeback-owner discipline so sealed worktree-bound verdicts stay fresh.

#### Scenario: XS change runs the full worktree lifecycle
- **WHEN** an XS change is applied
- **THEN** the skill SHALL run ensure → locator capture → apply → review → merge → cleanup in an isolated worktree, identical in shape to an M change

#### Scenario: No same-tree guidance survives on skill surfaces
- **WHEN** the canonical opsx-superpowers skill surfaces are inspected
- **THEN** no surface SHALL instruct or permit executing a change's implementation directly in the integration checkout

## MODIFIED Requirements

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
