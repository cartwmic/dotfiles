# Phase 10: Draft agents.md

**Mode:** Hybrid (subagent draft → user review)

**Reads:** All prior artifacts, existing AGENTS.md/CLAUDE.md if present

**Produces:** `docs/desloppify/agents-md-draft.md` (user places it in final location)

## Overview

Crystallize the codebase understanding gained during the audit into a reusable project reference document.

## Step 1: Dispatch Draft Subagent

Use `./prompts/agents-md-prompt.md`.

The subagent receives all desloppify artifacts plus any existing project docs.

If an existing AGENTS.md/CLAUDE.md is found: use it as the basis, integrate new understanding, lean toward concise if the existing doc is bloated.

If no existing document: produce a complete draft from scratch.

## Step 2: User Review

Present the draft section by section:
- "Does this accurately represent the architecture?"
- "Are these the right conventions to codify?"
- "Is this the right level of detail — too verbose anywhere?"
- "Anything critical missing that future agents should know?"
