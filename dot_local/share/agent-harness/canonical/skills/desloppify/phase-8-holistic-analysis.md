# Phase 8: Analyze Holistic View

**Mode:** Subagent

**Reads:** All prior artifacts

**Produces:** `docs/desloppify/holistic-analysis.md`

## Overview

Top-level architectural assessment that cross-references both enumeration sets and all prior analyses. This is where architectural-level improvements surface — things that can't be fixed by improving individual slices or even sets.

## Dispatch

Use `./prompts/holistic-analysis-prompt.md`.

**Context:** All artifacts from `docs/desloppify/`:
- `config.md`, `intelligence.md`, `holistic-view.md`
- `vertical-slices.md`, `horizontal-slices.md`
- `set-analysis-vertical.md`, `set-analysis-horizontal.md`
- Phase 6 analysis summaries (not full per-member details — extract key findings to keep context lean)

## What the Subagent Analyzes

### Architectural Fitness
- Does the actual architecture serve the project's needs?
- Are architectural boundaries in the right places?
- Are there architectural decisions that should be revisited?
- Is the architecture over-engineered or under-engineered for current needs?

### Cross-Cutting Improvements
- Improvements that span both vertical and horizontal sets
- Refactors that would benefit the entire codebase (not just one slice)
- Patterns that should be standardized project-wide

### Structural Risks
- Single points of failure (one module everything depends on)
- Knowledge silos (areas only one person understands)
- Fragile areas (high coupling + low test coverage + high churn)
- Scaling bottlenecks (if applicable)

### Health Trajectory
- Synthesize: is the codebase getting better or worse?
- Which areas are improving? Which are degrading?
- What's driving the trajectory? (team practices, tooling, architecture)

### Convention Recommendations
- Which existing conventions should be kept?
- Which should be updated or retired?
- What new conventions would improve consistency?
- Feed into Phase 12 (agents.md draft)

## Output Format

```markdown
# Holistic Analysis

## Architectural Fitness
[Assessment of whether architecture serves the project]

## Cross-Cutting Improvements

### [Improvement Title]
- **Scope:** [Which slices/sets affected]
- **Description:** [What to change]
- **Impact:** [Why this matters at the project level]
- **Effort:** [Rough estimate: Small/Medium/Large]
- **Dependencies:** [What else needs to change first]

[Repeat per improvement]

## Structural Risks
[Identified risks with severity and mitigation suggestions]

## Health Trajectory
[Overall assessment with supporting evidence]

## Convention Recommendations
- **Keep:** [Conventions that work well]
- **Update:** [Conventions that need revision]
- **Add:** [New conventions to introduce]
- **Retire:** [Conventions no longer serving the project]

## Summary
- Architectural fitness: [Strong/Adequate/Weak]
- Cross-cutting improvements: N
- Critical risks: N
- Overall trajectory: [Improving/Stable/Degrading]
```
