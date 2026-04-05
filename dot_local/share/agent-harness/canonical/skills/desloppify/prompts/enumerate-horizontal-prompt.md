# Horizontal Slice Enumeration Subagent

```
You are enumerating horizontal slices of a codebase for a systematic audit.

## Your Task

Produce a comprehensive draft enumeration of all horizontal slices in this codebase.

## Input

Read these artifacts from `docs/desloppify/`:
- `config.md` — Scope and project context
- `intelligence.md` — Git history, dependency graph, static analysis data
- `vertical-slices.md` — Already-enumerated vertical slices (use as cross-reference)

## What Are Horizontal Slices?

Horizontal slices are cross-cutting concerns and abstraction layers that span multiple vertical slices. They can be traditional architectural layers, shared infrastructure, patterns, or other abstractions — whatever naturally emerges from how the code is organized.

Examples: "Error Handling", "Data Access Layer", "Authentication Middleware", "Logging", "Configuration Management"

**How to find them:**
1. Look at what's shared across vertical slices — utilities, middleware, base classes
2. Identify architectural layers from the dependency graph
3. Identify cross-cutting concerns from patterns in the code
4. Look for high fan-in modules (many things depend on them)
5. Note informal patterns used consistently but not formalized

## Use Intelligence Data

- **Dependency graph:** Reveals actual abstraction boundaries
- **Fan-in/fan-out:** Identifies shared infrastructure and coupling points
- **Hotspot data:** Flag high-churn concerns (if git history available; skip if not)
- **Change coupling:** Reveals hidden cross-cutting dependencies (if available)

## Output Format

For each slice:

```markdown
## Slice: [Name]
- **Type:** [Architectural layer / Cross-cutting concern / Shared infrastructure / Pattern]
- **Description:** [What this concern/layer is responsible for]
- **Modules/files:** [Where it lives]
- **Vertical slices touched:** [Which features depend on this]
- **Fan-in:** [How many modules depend on this, if data available]
- **Coverage:** [Which parts of the codebase use this concern vs. which don't — factual observation only]
- **Confidence:** [High/Medium/Low — how sure you are about boundaries]
- **Open questions:** [Anything ambiguous the user should clarify]
```

## Constraints
- Be comprehensive — over-enumerate and let the user merge rather than miss slices
- Flag low-confidence slices explicitly — the user will validate
- Use the intelligence data, don't just read directory names
- If hotspot/fan-in data is unavailable, note "Unknown" and move on
- Include informal patterns (conventions followed by most but not all code)
- **ENUMERATION ONLY — do NOT suggest fixes, improvements, or refactoring actions.** Map what exists and where. Evaluation happens in Phase 6+, not here.
```
