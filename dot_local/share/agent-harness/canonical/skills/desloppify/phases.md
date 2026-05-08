# Desloppify Phase Reference

Lookup table for orchestrator: which file to read, which prompt to dispatch, what to read from disk, what to produce. The orchestrator never re-derives this — it reads it.

## Phase summary

| Phase | Mode | Instruction file | Prompt template(s) | Reads | Produces |
|-------|------|------------------|--------------------|-------|----------|
| 1 | Orchestrator-only | `./phase-1-configure.md` | — | Project docs | `config.md` |
| 2 | Subagent-only (parallel) | `./phase-2-intelligence.md` | `./prompts/intelligence-*.md` | `config.md` | `intelligence.md` |
| 3 | Hybrid | `./phase-3-vertical-slices.md` | `./prompts/enumerate-vertical-prompt.md` | config + intelligence | `vertical-slices.md` |
| 4 | Hybrid | `./phase-4-horizontal-slices.md` | `./prompts/enumerate-horizontal-prompt.md` | config + intelligence + vertical | `horizontal-slices.md` |
| 5 | Hybrid | `./phase-5-holistic-view.md` | `./prompts/holistic-view-prompt.md` | All prior artifacts | `holistic-view.md` |
| 6 | Hybrid (orchestrator triages, then 3–5 subagents) | `./phase-6-investigate.md` | `./prompts/investigate-concern-prompt.md` | holistic-view (flags) + source code | `investigation/concern-*.md` |
| 7 | Subagent-only | `./phase-7-consolidate-plan.md` | `./prompts/plan-draft-prompt.md` | holistic-view + investigations | `desloppify-plan-draft.md` |
| 8 | Subagent-only (parallel: blind + contextual) | `./phase-8-adversarial-review.md` | `./prompts/review-blind-prompt.md`, `./prompts/review-contextual-prompt.md` | Plan + codebase (blind) / All (contextual) | `review-blind.md`, `review-contextual.md` |
| 9 | Hybrid (socratic with user) | `./phase-9-finalize-plan.md` | — | Plan draft + both reviews | `desloppify-plan.md` |
| 10 | Hybrid | `./phase-10-agents-md.md` | `./prompts/agents-md-prompt.md` | All artifacts + existing docs | `agents-md-draft.md` |

## Execution modes

**Orchestrator-only** (Phase 1): Orchestrator works directly with the user, then writes the artifact.

**Subagent-only** (Phases 2, 7, 8): Orchestrator reads the phase instruction file, dispatches subagent(s) with the prompt template, then handles the artifact per the return pattern below.

**Hybrid** (Phases 3, 4, 5, 6, 9, 10): Orchestrator dispatches a subagent for the first pass (Phase 6 triages flags first), presents the result to the user for socratic review/refinement, then writes the final artifact.

## Subagent return patterns

| Phases | Pattern | Why |
|--------|---------|-----|
| 2–5 | **Merge/refine.** Subagent returns full structured output to the orchestrator. Orchestrator merges (Phase 2) or refines with the user (Phases 3–5), then writes the final artifact. | Orchestrator needs the full content to do its merge/refinement job. |
| 6–8, 10 | **Write-to-disk.** Subagent writes its full output directly to the artifact file and returns only a brief summary. Success is verified by checking the artifact exists. | Keeps the orchestrator's context lean; the artifact is the deliverable. |

## Flags for investigation

Phases 2–5 each end with a **Flags for Investigation** section. A flag is one line:

> **location + what was observed + why it caught attention**

Flags are factual observations, not diagnoses or fix suggestions. Phase 6 collects all flags, groups them into concern themes, presents the grouping to the user for validation, then dispatches 3–5 focused investigation subagents — one per concern theme, not one per slice.
