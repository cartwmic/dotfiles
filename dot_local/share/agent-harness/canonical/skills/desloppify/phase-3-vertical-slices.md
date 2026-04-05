# Phase 3: Enumerate Vertical Slices

**Mode:** Hybrid (subagent draft → user refinement)

**Reads:** `docs/desloppify/config.md`, `docs/desloppify/intelligence.md`

**Produces:** `docs/desloppify/vertical-slices.md`

## Overview

Vertical slices are feature-oriented end-to-end paths through the codebase. Each slice represents a user-facing capability traced through all layers it touches.

## Step 1: Dispatch Enumeration Subagent

Use `./prompts/enumerate-vertical-prompt.md`.

The subagent reads the intelligence artifact and project structure to produce a draft enumeration. It should:
- Identify entry points (routes, commands, event handlers, UI components)
- Trace each entry point through the layers it touches
- Use hotspot data to flag high-churn slices
- Use change coupling data to identify slices that may be entangled
- Name each slice clearly by its user-facing capability

## Step 2: Present Draft to User

Show the draft enumeration. For each slice, show:
- **Name** — The capability (e.g., "User Authentication")
- **Entry points** — Where it starts (route, command, etc.)
- **Files/modules touched** — The path through the codebase
- **Hotspot indicator** — High/medium/low based on intelligence data

## Step 3: Socratic Refinement

Ask the user to validate and extend, one question at a time:

- "Does this list capture all the major features? What's missing?"
- "Are any of these actually the same slice that I've split incorrectly?"
- "Are any of these too broad and should be split?"
- "I flagged X as high-churn — does that match your experience?"
- "The change coupling data suggests A and B are entangled — is that intentional?"

**Stay focused on enumeration — if the user or subagent starts identifying problems to fix, redirect: "Good observation — I'll capture that for Phase 6 analysis. For now, let's finish mapping what exists."**

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
```
