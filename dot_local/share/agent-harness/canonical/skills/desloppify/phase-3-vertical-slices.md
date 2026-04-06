# Phase 3: Enumerate Vertical Slices

**Mode:** Hybrid (subagent draft → user refinement)

**Reads:** `docs/desloppify/config.md`, `docs/desloppify/intelligence.md`

**Produces:** `docs/desloppify/vertical-slices.md`

## Overview

Vertical slices are feature-oriented end-to-end paths through the codebase. Each slice represents a user-facing capability traced through all layers it touches.

## Step 1: Dispatch Enumeration Subagent

Use `./prompts/enumerate-vertical-prompt.md`.

The subagent reads the intelligence artifact and project structure to produce a draft enumeration with flags for notable observations.

## Step 2: Present Draft to User

Show the draft enumeration. For each slice, show:
- **Name** — The capability
- **Entry points** — Where it starts
- **Files/modules touched** — The path through the codebase
- **Hotspot indicator** — High/medium/low from intelligence data

## Step 3: Socratic Refinement

Ask the user to validate and extend, one question at a time:

- "Does this list capture all the major features? What's missing?"
- "Are any of these actually the same slice that I've split incorrectly?"
- "Are any of these too broad and should be split?"
- "I flagged X as high-churn — does that match your experience?"
- "The change coupling data suggests A and B are entangled — is that intentional?"

Stay focused on enumeration. If observations about issues come up, capture them as flags: "Good observation — I'll add that as a flag for Phase 6 investigation."

Iterate until the user confirms the enumeration is complete.

## Step 4: Write Artifact

Write `docs/desloppify/vertical-slices.md`:

```markdown
# Vertical Slices

## Slice: [Name]
- **Capability:** [What it does for users]
- **Entry points:** [Routes, commands, handlers]
- **Files/modules:** [List of files this slice touches]
- **Hotspot level:** [High/Medium/Low]
- **Change coupling:** [Other slices this is coupled with]
- **Notes:** [User-provided context, known issues]

[Repeat per slice]

## Summary
- Total slices: N
- High-churn slices: [list]
- Entangled slices: [pairs]

## Flags for Investigation
[Merge subagent flags + any user-surfaced observations]
- **[location]** — [observation] — [why notable]
```
