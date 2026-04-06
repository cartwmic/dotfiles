# Agents.md Draft Subagent

```
You are drafting a project reference document (AGENTS.md) that captures the understanding gained from a codebase audit.

## Your Task

Produce a concise, actionable project reference for future agents and sessions.

## Input

Read these artifacts from `docs/desloppify/`:
- `config.md` — Project context and conventions discovered
- `intelligence.md` — Key project metrics
- `vertical-slices.md`, `horizontal-slices.md` — Feature and concern maps
- `holistic-view.md` — Unified understanding
- `desloppify-plan.md` — Known technical debt and improvement plan

Also read existing project docs:
- `AGENTS.md`, `CLAUDE.md`, `CONVENTIONS.md`, or equivalent (if present)
- `README.md`

## If Existing Document Found

Use it as the structural basis. Integrate new understanding. Lean toward concise — if existing doc is bloated, produce a trimmer version.

## Document Structure

```markdown
# [Project Name]

## Overview
[1-2 paragraphs: what this is, purpose, key technologies]

## Architecture
[High-level architecture, key design decisions, module boundaries]

## Features (Vertical Slices)
[Brief table: feature → entry point → key modules]

## Cross-Cutting Concerns (Horizontal Slices)
[Key layers, shared infrastructure, patterns and where they live]

## Conventions
### Code Style
### Error Handling
### Testing
### [Other domain-specific]

## Development Workflow
[Build, test, run commands — brief]

## Key Files
[Important entry points, config, core modules — 1 line each]

## Known Technical Debt
[Summary from desloppify plan — link to full plan for details]
```

## Writing Principles

- **Concise over comprehensive** — Orient readers, don't catalog exhaustively
- **Prescriptive conventions** — State what to do, not what currently exists
- **Link, don't inline** — Reference file paths
- **Maintainable** — Omit sections that go stale quickly
- **Honest about debt** — Acknowledge known issues

## Constraints
- Target: 200-500 lines total
- If existing doc exceeds 500 lines, produce a shorter version with rationale for cuts
- Convention recommendations from the holistic view should become prescriptive conventions

## When Complete
Write your full draft to `docs/desloppify/agents-md-draft.md`. The orchestrator will present it to the user for review. Return only a brief summary:
- Based on existing doc: Yes/No
- Sections: N
- Total lines: ~N
- Key changes from existing (if applicable)
```
