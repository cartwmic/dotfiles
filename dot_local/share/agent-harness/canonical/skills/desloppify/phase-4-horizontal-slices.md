# Phase 4: Enumerate Horizontal Slices

**Mode:** Hybrid (subagent draft → user refinement)

**Reads:** `docs/desloppify/config.md`, `docs/desloppify/intelligence.md`, `docs/desloppify/vertical-slices.md`

**Produces:** `docs/desloppify/horizontal-slices.md`

## Overview

Horizontal slices are cross-cutting concerns and abstraction layers. These span across multiple vertical slices at the same conceptual level. They can be traditional architectural layers, shared infrastructure, patterns, or other abstractions — whatever naturally emerges from how the code is organized.

## Step 1: Dispatch Enumeration Subagent

Use `./prompts/enumerate-horizontal-prompt.md`.

The subagent reads intelligence + vertical slices to produce a draft. It should:
- Identify architectural layers (if present): presentation, business logic, data access, etc.
- Identify cross-cutting concerns: error handling, logging, auth, validation, config, etc.
- Identify shared infrastructure: utilities, helpers, base classes, middleware, etc.
- Use dependency graph data to reveal actual abstraction boundaries
- Use fan-in/fan-out data to identify highly-depended-upon modules
- Note where vertical slices share horizontal infrastructure

## Step 2: Present Draft to User

Show the draft enumeration. For each slice, show:
- **Name** — The concern or layer (e.g., "Error Handling", "Data Access Layer")
- **Type** — Architectural layer / cross-cutting concern / shared infrastructure / pattern
- **Modules/files** — Where this concern lives in the codebase
- **Vertical slices touched** — Which vertical slices depend on this
- **Fan-in** — How many modules depend on this

## Step 3: Socratic Refinement

Ask the user to validate and extend, one question at a time:

- "Does this capture the major cross-cutting concerns? What am I missing?"
- "I've categorized X as an architectural layer — is that how you think about it?"
- "The dependency data shows Y is depended on by almost everything — is that intentional?"
- "Are there informal patterns (not enforced, but conventionally followed) that I should include?"
- "Any concerns or layers that exist in some parts of the codebase but not others?"

Iterate until the user confirms the enumeration is complete.

## Step 4: Write Artifact

Write `docs/desloppify/horizontal-slices.md`:

```markdown
# Horizontal Slices

## Slice: [Name]
- **Type:** [Architectural layer / Cross-cutting concern / Shared infrastructure / Pattern]
- **Description:** [What this concern/layer is responsible for]
- **Modules/files:** [Where it lives]
- **Vertical slices touched:** [Which features depend on this]
- **Fan-in:** [Number of dependents]
- **Consistency:** [Is it applied uniformly or patchy?]
- **Notes:** [User-provided context]

[Repeat per slice]

## Summary
- Total slices: N
- By type: [count per type]
- Most depended-upon: [top 3]
- Patchily applied: [list of inconsistent concerns]
```
