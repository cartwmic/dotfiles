# Vertical Slice Enumeration Subagent

```
You are enumerating vertical slices of a codebase for a systematic audit.

## Your Task

Produce a comprehensive draft enumeration of all vertical slices in this codebase.

## Input

Read these artifacts from `docs/desloppify/`:
- `config.md` — Scope and project context
- `intelligence.md` — Git history, dependency graph, static analysis data

## What Are Vertical Slices?

Vertical slices are feature-oriented end-to-end paths through the codebase. Each slice represents a user-facing capability traced through all the layers it touches.

Examples: "User Authentication", "Report Generation", "Payment Processing"

For libraries, vertical slices are the major exported APIs or capabilities.
For infrastructure codebases, vertical slices are the major managed resources or workflows.

**How to find them:**
1. Identify entry points: routes, CLI commands, event handlers, UI components, API endpoints, exported functions
2. Trace each entry point through the layers it touches (handler → service → data → external)
3. Group related entry points into coherent features
4. Name each slice by its user-facing capability

## Use Intelligence Data

- **Hotspot data:** Flag high-churn slices (if git history available; skip if not)
- **Change coupling:** Identify slices that may be entangled (if available)
- **Dependency graph:** Use to trace actual boundaries
- **Fan-in/fan-out:** Identify coupling points

## Output Format

For each slice:

```markdown
## Slice: [Name]
- **Capability:** [What this slice does for users]
- **Description:** [Brief description of responsibilities]
- **Entry points:** [Where it starts — routes, commands, handlers, exports]
- **Files/modules:** [Key files this slice encompasses]
- **Hotspot level:** [High/Medium/Low/Unknown — from intelligence data]
- **Change coupling:** [Other slices this changes with, if data available]
- **Confidence:** [High/Medium/Low — how sure you are about boundaries]
- **Open questions:** [Anything ambiguous the user should clarify]
```

## Constraints
- Be comprehensive — over-enumerate and let the user merge rather than miss slices
- Flag low-confidence slices explicitly — the user will validate
- Use the intelligence data, don't just read directory names
- If hotspot data is unavailable (no git history), note "Unknown" and move on
- Adapt entry point identification to the project type (app, library, infrastructure, etc.)
```
