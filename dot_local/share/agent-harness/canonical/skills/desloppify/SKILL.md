---
name: desloppify
description: Use when code quality has degraded, architecture has drifted, conventions are inconsistent, or you need a comprehensive codebase improvement plan before refactoring — for medium-to-large codebases with enough complexity to warrant systematic analysis
---

# Desloppify

## Overview

Systematic codebase audit. Map the terrain (vertical slices, horizontal slices, holistic view), flag observations that warrant investigation, then dispatch focused concern-based analysis to produce a prioritized cleanup plan.

**Core principle:** Understand first, diagnose second. Phases 1–5 build structural understanding and flag observations. Phase 6 investigates the flagged concerns. Phases 7–10 consolidate, review, and finalize.

**Announce at start:** "I'm using the desloppify skill to systematically audit this codebase."

## When to use

- Codebase has accumulated technical debt across multiple features/layers
- Architecture has drifted from its original design
- Conventions are inconsistent or undocumented
- You need a prioritized improvement plan before a major refactoring effort
- Onboarding to an unfamiliar codebase and want to understand it systematically

## When NOT to use

- **Tiny codebases (< ~10 files)** — Just read the code and make a plan directly.
- **Targeted fix for a known issue** — Use systematic-debugging or just fix it.
- **Emergency hotfix** — This is a multi-hour process. Fix the fire first.
- **Single PR review** — Use a code-review skill instead.
- **Monorepos without scoping** — Scope to one subsystem per run.

## Pipeline

10 sequential phases. Each phase reads prior artifacts from disk; subagents never re-derive what's already written.

1. **Configure** — orchestrator + user agree on scope, criteria, verification
2. **Gather Intelligence** — parallel subagents
3. **Enumerate Vertical Slices** — features/user journeys
4. **Enumerate Horizontal Slices** — layers/cross-cutting concerns
5. **Synthesize Holistic View** — combined picture + flags
6. **Triage + Investigate Concerns** — orchestrator triages flags, dispatches 3–5 concern-focused subagents
7. **Consolidate Plan Draft**
8. **Adversarial Review** — parallel blind + contextual reviewers
9. **Finalize Plan** — socratic with user
10. **Draft agents.md**

All artifacts go to `docs/desloppify/` (or user-specified location).

**For phase-by-phase instruction files, prompt templates, execution modes, return patterns, and flag rules, see [phases.md](./phases.md).**

## Common mistakes

- **Diagnosing before understanding.** Phases 1–5 only flag and observe. Pushing fixes early biases the holistic view and wastes subagent context.
- **Subagent reads conversation history instead of disk.** Subagents must read `docs/desloppify/` artifacts. If a subagent prompt depends on chat context, the resume case (next session) breaks.
- **Skipping user validation on hybrid phases.** No hybrid phase output is final without user approval. "It looks fine" without showing the user is a silent corruption.
- **One investigation subagent per slice.** Phase 6 dispatches by **concern theme**, not by slice. 30 slices ≠ 30 subagents.
- **Orchestrator absorbs full subagent output in Phases 6–8, 10.** Those subagents own the artifact; the orchestrator gets only a brief summary. Pulling full text bloats orchestrator context.
- **Merging without refining (Phases 3–5).** Subagent output is a draft. The orchestrator must run socratic refinement with the user, not paste-and-write.
- **Inventing criteria/verification instead of extending defaults.** See `default-criteria.md` and `default-verification.md`. Override; don't replace.

## Red flags — STOP

If you catch yourself thinking any of these, stop and restart the correct path:

- "I'll just write the plan now, I've seen enough."
- "The user doesn't need to validate this phase, it's obvious."
- "I'll dispatch one subagent per slice — it's more thorough."
- "Let me put the full subagent output in my context so I can reason about it."
- "I'll read the prior phase from chat history instead of opening the artifact."
- "This codebase has no tests / no git history / one developer, so desloppify won't work." (Graceful degradation handles all three. Configure in Phase 1.)

## Resuming a partial run

All phase outputs are written to `docs/desloppify/` as they complete. To resume:

1. Start a new session and invoke desloppify
2. Point to the existing `docs/desloppify/` directory
3. The orchestrator checks which artifacts exist and resumes from the next incomplete phase

## Integration

- **adversarial-review-cycle** — Phase 8 already uses adversarial review internally; the broader skill applies if you want pressure-testing on the *finalized* plan before execution.
- **pi-subagents** — Execute the plan task-by-task with subagent delegation and review gates.
- **review-plans** — Useful for an extra plan-quality pass between Phase 9 and execution.

**After desloppify completes**, offer the user:

1. Hand the plan to an execution workflow (pi-subagents, manual, etc.)
2. Save artifacts and revisit later
3. Execute specific high-priority items immediately
