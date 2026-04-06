# Phase 4: Enumerate Horizontal Slices

**Mode:** Hybrid (subagent draft → user refinement)

**Reads:** `docs/desloppify/config.md`, `docs/desloppify/intelligence.md`, `docs/desloppify/vertical-slices.md`

**Produces:** `docs/desloppify/horizontal-slices.md`

## Overview

Horizontal slices are cross-cutting concerns and abstraction layers that span multiple vertical slices. They can be traditional architectural layers, shared infrastructure, patterns, or other abstractions — whatever naturally emerges from how the code is organized.

## Step 1: Dispatch Enumeration Subagent

**Model selection:** Use the analytical-tier model.

Use `./prompts/enumerate-horizontal-prompt.md`.

The subagent reads intelligence + vertical slices to produce a draft with flags for notable observations.

## Step 2: Present Draft to User

Show the draft enumeration. For each slice, show:
- **Name** — The concern or layer
- **Type** — Architectural pattern / layer / cross-cutting concern / shared infrastructure / informal pattern
- **Modules/files** — Where it lives
- **Vertical slices touched** — Which vertical slices depend on this

## Step 3: Socratic Refinement

Ask the user to validate and extend, one question at a time:

- "Does this capture the major cross-cutting concerns? What am I missing?"
- "I've categorized X as an architectural layer — is that how you think about it?"
- "The dependency data shows Y is depended on by almost everything — is that intentional?"
- "Are there informal patterns (not enforced, but conventionally followed) that I should include?"
- "Does this codebase follow an overarching architectural pattern (e.g., clean architecture, hexagonal) that should be its own horizontal slice?"

Stay focused on enumeration. If observations about issues come up, capture them as flags: "Good observation — I'll add that as a flag for Phase 6 investigation."

Iterate until the user confirms the enumeration is complete.

## Step 4: Write Artifact

Write `docs/desloppify/horizontal-slices.md`:

```markdown
# Horizontal Slices

## Slice: [Name]
- **Type:** [Architectural pattern / Architectural layer / Cross-cutting concern / Shared infrastructure / Informal pattern]
- **Description:** [What this concern/layer is responsible for]
- **Modules/files:** [Where it lives]
- **Vertical slices touched:** [Which features depend on this]
- **Fan-in:** [Number of dependents]
- **Coverage:** [Which parts of the codebase use this vs. which don't]
- **Notes:** [User-provided context]

[Repeat per slice]

## Summary
- Total slices: N
- By type: [count per type]
- Most depended-upon: [top 3]

## Flags for Investigation
[Merge subagent flags + any user-surfaced observations]
- **[location]** — [observation] — [why notable]
```
