# Agents.md Draft Subagent

```
You are drafting a project reference document (AGENTS.md) that captures the understanding gained from a codebase audit.

## Your Task

Produce a concise, actionable project reference for future agents and sessions.

## Input

**Read ALL artifacts from `docs/desloppify/`:**
- `config.md` — Project context and conventions discovered
- `intelligence.md` — Key project metrics
- `vertical-slices.md`, `horizontal-slices.md` — Feature and concern maps
- `holistic-view.md` — Unified understanding
- `holistic-analysis.md` — Convention recommendations
- `desloppify-plan.md` — Known technical debt

**Also read existing project docs:**
- `AGENTS.md`, `CLAUDE.md`, `CONVENTIONS.md`, or equivalent (if present)
- `README.md`

## If Existing Document Found

- Use it as the structural basis
- Integrate new understanding from the audit
- **Lean toward concise** — if existing doc is bloated, produce a trimmer version
- In a separate section at the end, note what changed and why

## If No Existing Document

Produce a complete draft from scratch.

## Document Structure

```markdown
# [Project Name]

## Overview
[1-2 paragraphs: what this is, purpose, key technologies, primary users]

## Architecture
[High-level architecture description]
[Key design decisions and rationale]
[Module/component boundaries]

## Features (Vertical Slices)
[Brief table or list: feature → entry point → key modules]
[Not exhaustive — orient, don't catalog]

## Cross-Cutting Concerns (Horizontal Slices)
[Key layers, shared infrastructure, patterns]
[Where each concern lives in the codebase]

## Conventions

### Code Style
[Naming, formatting, file organization]

### Error Handling
[How errors should be handled — the standard pattern]

### Testing
[Testing approach, conventions, where tests live]

### [Other domain-specific conventions]

## Development Workflow
[How to build, test, run, deploy]
[Key commands — brief, not a tutorial]

## Key Files
[Important entry points, config files, core modules]
[Brief description of each — 1 line]

## Known Technical Debt
[Summary from desloppify plan — acknowledged debt with status]
[Link to full desloppify plan for details]
```

## Writing Principles

- **Concise over comprehensive** — Orient readers, don't exhaustively catalog. Future agents can read code.
- **Prescriptive conventions** — State what to do: "Use Result<T, E> for error handling" not "Some modules use Result, some use exceptions"
- **Link, don't inline** — Reference file paths rather than copying content
- **Maintainable** — If a section goes stale quickly, either make it auto-generated or leave it out
- **Honest about debt** — Acknowledge known issues; pretending debt doesn't exist is worse than documenting it
- **Actionable** — Every section should help someone make a decision or find something

## Constraints
- Target: 200-500 lines total (not counting code blocks)
- If existing doc is over 500 lines, the draft should be shorter with a rationale for what was cut
- Don't duplicate README content — reference it
- Don't include transient information (current sprint, recent changes)
- Convention recommendations from Phase 8 holistic analysis should be incorporated as prescriptive conventions
```
