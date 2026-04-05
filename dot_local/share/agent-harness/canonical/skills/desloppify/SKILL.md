---
name: desloppify
description: Use when code quality has degraded, architecture has drifted, conventions are inconsistent, or you need a comprehensive codebase improvement plan before refactoring — for medium-to-large codebases with enough complexity to warrant systematic analysis
---

# Desloppify

## Overview

Systematic codebase audit that maps vertical slices (features end-to-end), horizontal slices (cross-cutting concerns/layers), and synthesizes a holistic view — then analyzes at every level to produce a prioritized, actionable cleanup plan.

**Core principle:** Map the terrain completely before proposing changes. The orchestrator manages flow and user interaction. Subagents do the heavy analytical work. Disk artifacts carry context between phases.

**Announce at start:** "I'm using the desloppify skill to systematically audit this codebase."

## When to Use

- Codebase has accumulated technical debt across multiple features/layers
- Architecture has drifted from its original design
- Conventions are inconsistent or undocumented
- You need a prioritized improvement plan before a major refactoring effort
- Onboarding to an unfamiliar codebase and want to understand it systematically

## When NOT to Use

- **Tiny codebases (< ~10 files)** — Just read the code and make a plan directly. 12 phases for 3 files is absurd overhead.
- **Targeted fix for a known issue** — Use systematic-debugging or just fix it.
- **Emergency hotfix** — This is a multi-hour process. Fix the fire first.
- **Single PR review** — Use requesting-code-review instead.
- **Monorepos without scoping** — Scope to one subsystem per run. For monorepos with 30+ features, the Phase 6 parallelism and Phase 9 context load become prohibitive without scoping.

## Artifact Directory

All phase outputs go to `docs/desloppify/` (or user-specified location). Each phase reads prior artifacts — subagents never re-gather what's already on disk.

## Orchestrator Flow

```dot
digraph desloppify {
    rankdir=TB;

    phase1 [label="Phase 1: Configure\n(orchestrator + user)" shape=box];
    phase2 [label="Phase 2: Gather Intelligence\n(parallel subagents)" shape=box];
    phase3 [label="Phase 3: Enumerate Vertical Slices\n(subagent draft → user refinement)" shape=box];
    phase4 [label="Phase 4: Enumerate Horizontal Slices\n(subagent draft → user refinement)" shape=box];
    phase5 [label="Phase 5: Synthesize Holistic View\n(subagent draft → user validation)" shape=box];
    phase6 [label="Phase 6: Analyze Each Member\n(parallel subagents per slice)" shape=box];
    phase7 [label="Phase 7: Analyze Each Set\n(subagent)" shape=box];
    phase8 [label="Phase 8: Analyze Holistic View\n(subagent)" shape=box];
    phase9 [label="Phase 9: Consolidate Plan Draft\n(subagent)" shape=box];
    phase10 [label="Phase 10: Adversarial Review\n(parallel subagents: blind + contextual)" shape=box];
    phase11 [label="Phase 11: Finalize Plan\n(socratic with user)" shape=box];
    phase12 [label="Phase 12: Draft agents.md\n(subagent draft → user review)" shape=box];

    phase1 -> phase2;
    phase2 -> phase3;
    phase3 -> phase4;
    phase4 -> phase5;
    phase5 -> phase6;
    phase6 -> phase7;
    phase7 -> phase8;
    phase8 -> phase9;
    phase9 -> phase10;
    phase10 -> phase11;
    phase11 -> phase12;
}
```

## Phase Execution Pattern

Each phase follows one of two patterns:

**Subagent-only** (Phases 2, 6, 7, 8, 9, 10):
1. Read phase instruction file (e.g., `./phase-2-intelligence.md`)
2. Dispatch subagent(s) with corresponding prompt template from `./prompts/`
3. Review subagent output for completeness
4. Write artifact to `docs/desloppify/`
5. Proceed to next phase

**Hybrid** (Phases 3, 4, 5, 11, 12):
1. Read phase instruction file
2. Dispatch subagent for autonomous first pass (except Phase 11 which uses Phase 9+10 outputs)
3. Present draft to user for review/refinement (socratic)
4. Iterate until user approves
5. Write final artifact to `docs/desloppify/`
6. Proceed to next phase

**Orchestrator-only** (Phase 1):
1. Read phase instruction file
2. Work directly with user
3. Write artifact to `docs/desloppify/`

## Phase Summary

| Phase | Instruction File | Prompt Template(s) | Reads | Produces |
|-------|-----------------|--------------------:|-------|----------|
| 1 | `./phase-1-configure.md` | — | Project docs | `config.md` |
| 2 | `./phase-2-intelligence.md` | `./prompts/intelligence-*.md` | `config.md` | `intelligence.md` |
| 3 | `./phase-3-vertical-slices.md` | `./prompts/enumerate-vertical-prompt.md` | `intelligence.md` | `vertical-slices.md` |
| 4 | `./phase-4-horizontal-slices.md` | `./prompts/enumerate-horizontal-prompt.md` | `intelligence.md` | `horizontal-slices.md` |
| 5 | `./phase-5-holistic-view.md` | `./prompts/holistic-view-prompt.md` | Both slices + intelligence | `holistic-view.md` |
| 6 | `./phase-6-member-analysis.md` | `./prompts/member-analysis-prompt.md` | All above | `analysis/vertical-<name>.md`, `analysis/horizontal-<name>.md` per slice |
| 7 | `./phase-7-set-analysis.md` | `./prompts/set-analysis-vertical-prompt.md`, `./prompts/set-analysis-horizontal-prompt.md` | All above + Phase 6 | `set-analysis-vertical.md`, `set-analysis-horizontal.md` |
| 8 | `./phase-8-holistic-analysis.md` | `./prompts/holistic-analysis-prompt.md` | All above | `holistic-analysis.md` |
| 9 | `./phase-9-consolidate-plan.md` | `./prompts/plan-draft-prompt.md` | All above | `desloppify-plan-draft.md` |
| 10 | `./phase-10-adversarial-review.md` | `./prompts/review-blind-prompt.md`, `./prompts/review-contextual-prompt.md` | Plan draft + codebase (blind) / All artifacts (contextual) | `review-blind.md`, `review-contextual.md` |
| 11 | `./phase-11-finalize-plan.md` | — | Plan draft + both reviews | `desloppify-plan.md` |
| 12 | `./phase-12-agents-md.md` | `./prompts/agents-md-prompt.md` | All above | `agents.md` (draft) |

## Key Principles

- **Orchestrator stays lean** — dispatches work, facilitates user interaction, never does heavy analysis itself
- **Artifacts carry context** — subagents read disk, not conversation history
- **Parallel where possible** — Phase 2 (3 parallel intelligence subagents), Phase 6 (one subagent per slice), Phase 10 (blind + contextual reviewers)
- **User validates every hybrid phase** — no phase output is final without user approval
- **Incremental execution** — the final plan produces independently-deployable improvements
- **Adversarial review before finalization** — blind and context-aware reviewers challenge the plan before the user commits
- **Sensible defaults, always overridable** — criteria and verification methods have defaults the user extends
- **Graceful degradation** — missing git history, no tests, no linter, solo developer projects all handled with explicit fallback guidance

## Resuming a Partial Run

All phase outputs are written to `docs/desloppify/` as they complete. If a session ends mid-pipeline:

1. Start a new session and invoke desloppify
2. Point to the existing `docs/desloppify/` directory
3. The orchestrator checks which artifacts exist and resumes from the next incomplete phase
4. User-validated artifacts (from hybrid phases) don't need re-validation unless the user requests it

## Integration

**Works well with:**
- **superpowers:writing-plans** — Desloppify plan can feed into writing-plans for detailed implementation
- **superpowers:executing-plans** — Execute the desloppify plan task-by-task
- **superpowers:dispatching-parallel-agents** — Phase 2 and 6 use parallel dispatch pattern
- **superpowers:subagent-driven-development** — Execute improvements with review gates

**After desloppify completes**, offer the user:
1. Feed the plan into writing-plans for detailed implementation planning
2. Save artifacts and revisit later
3. Execute specific high-priority items immediately
