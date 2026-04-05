# Phase 12: Draft agents.md

**Mode:** Hybrid (subagent draft → user review)

**Reads:** All prior artifacts, existing AGENTS.md/CLAUDE.md if present

**Produces:** `docs/desloppify/agents-md-draft.md` (user places it in final location)

## Overview

Crystallize the codebase understanding gained during the audit into a reusable project reference document. This captures architecture, conventions, and design decisions so future sessions and agents can understand the codebase without rediscovering everything.

## Step 1: Dispatch Draft Subagent

Use `./prompts/agents-md-prompt.md`.

The subagent receives:
- All `docs/desloppify/` artifacts
- Existing AGENTS.md, CLAUDE.md, or equivalent (if found during Phase 1)
- Convention recommendations from Phase 8

### If Existing Document Found

The subagent should:
- Use the existing document as the structural basis
- Integrate new understanding from the audit
- **Lean toward concise** — if existing doc is bloated, suggest trimming
- Call out what's new vs. what was already documented
- Flag sections that are stale or contradict findings

### If No Existing Document

The subagent produces a complete draft from scratch based on audit findings.

## Step 2: User Review

Present the draft to the user. Walk through section by section:

- "Here's the draft. I'll go through it section by section."
- "Does this accurately represent the architecture?"
- "Are these the right conventions to codify?"
- "Is this the right level of detail — too verbose anywhere?"
- "Anything critical missing that future agents should know?"

## Document Structure

```markdown
# [Project Name]

## Overview
[One paragraph: what this project is, its purpose, key technologies]

## Architecture
[High-level architecture — from holistic view]
[Key architectural decisions and rationale]

## Vertical Slices (Features)
[Brief summary of each feature and its path through the codebase]

## Horizontal Slices (Cross-Cutting Concerns)
[Key layers and cross-cutting concerns with their locations]

## Conventions
[Coding conventions — both existing and newly recommended]
[File organization conventions]
[Testing conventions]
[Error handling conventions]

## Development Workflow
[How to build, test, run]
[Key commands]

## Known Technical Debt
[Summary from desloppify plan — what's acknowledged and planned]

## Key Files
[Important files and what they do — entry points, config, core modules]
```

## Principles for the Draft

- **Concise over comprehensive** — Future agents can always read code. The doc should orient, not exhaustively catalog.
- **Conventions are prescriptive** — State what to do, not what currently exists (unless documenting debt).
- **Link, don't inline** — Reference files by path rather than copying content.
- **Keep it maintainable** — If a section will go stale quickly, either automate it or leave it out.
