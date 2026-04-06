# Phase 5: Synthesize Holistic View

**Mode:** Hybrid (subagent draft → user validation)

**Reads:** `docs/desloppify/config.md`, `docs/desloppify/intelligence.md`, `docs/desloppify/vertical-slices.md`, `docs/desloppify/horizontal-slices.md`

**Produces:** `docs/desloppify/holistic-view.md`

## Overview

Combine vertical and horizontal slice enumerations with intelligence data into a unified understanding of the codebase. This becomes the reference lens for Phase 6 investigation. The holistic view also collects and consolidates all flags from prior phases.

## Step 1: Dispatch Synthesis Subagent

Use `./prompts/holistic-view-prompt.md`.

The subagent reads all four input artifacts and produces a draft holistic view covering:
- Interaction map (vertical × horizontal intersections)
- Structural health signals (coupling, coverage gaps, consistency, architectural alignment)
- Codebase trajectory (improving/degrading/stable)
- Technical debt concentration
- Consolidated flags from all prior phases plus new flags from the synthesis

## Step 2: Present to User

Walk the user through the holistic view section by section. After each section:

"Does this match your mental model of the codebase? Anything feel off?"

Focus especially on:
- Surprises — things the data reveals that contradict expectations
- Blind spots — areas the user knows are problematic but didn't show up
- Disputed interpretations — where the data could be read multiple ways

## Step 3: Write Artifact

Write `docs/desloppify/holistic-view.md`:

```markdown
# Holistic View

## Interaction Map
[Matrix or narrative showing vertical × horizontal intersections]

## Structural Health
### Coupling Hotspots
[Areas of unexpected entanglement]

### Coverage Gaps
[Horizontal concerns missing from vertical slices]

### Consistency Patterns
[Where the codebase is uniform vs. fragmented]

### Architectural Alignment
[Actual vs. intended architecture]

## Codebase Trajectory
[Improving / degrading / stable, by area]

## Technical Debt Concentration
[Where debt is concentrated and why]

## User-Validated Observations
[Key points the user confirmed, corrected, or added]

## Consolidated Flags for Investigation
[ALL flags from Phases 2-5, deduplicated and organized by theme]
- **[location]** — [observation] — [why notable] — [source: Phase N]
```
