# Phase 10: Adversarial Review

**Mode:** Parallel subagents (blind + context-aware)

**Reads:** See per-reviewer details below

**Produces:** `docs/desloppify/review-blind.md`, `docs/desloppify/review-contextual.md`

## Overview

Two independent reviewers challenge the plan draft before the user finalizes it. They run in parallel and have deliberately different levels of context to catch different classes of problems.

## Why Two Reviewers

The analysis pipeline (Phases 2-9) builds an accumulated understanding. This is powerful but creates confirmation bias risk — if early phases mischaracterized something, that error propagates through every subsequent phase unchallenged.

- **Blind reviewer** breaks the confirmation chain by looking at the code with fresh eyes
- **Context-aware reviewer** stress-tests internal consistency of the full analysis chain

Together they catch both "wrong conclusions from the evidence" and "wrong evidence in the first place."

## Reviewer 1: Blind Review

**Prompt:** `./prompts/review-blind-prompt.md`

**Gets:**
- The codebase itself (can read all source files)
- `docs/desloppify/desloppify-plan-draft.md`
- `docs/desloppify/config.md` (criteria and verification methods only)

**Does NOT get:** intelligence, slice enumerations, analysis artifacts, holistic view — nothing from Phases 2-8.

**Job:** Look at the code independently and assess:
- Does this plan target the right problems?
- What obvious issues does the plan miss?
- Are any plan items unjustified by the actual code?
- Is the prioritization sensible from a fresh perspective?
- Are effort/risk estimates realistic based on the code?

**Value:** Catches groupthink, normalized assumptions, blind spots in the analysis pipeline.

## Reviewer 2: Context-Aware Review

**Prompt:** `./prompts/review-contextual-prompt.md`

**Gets:** Everything — all artifacts from `docs/desloppify/` including the plan draft.

**Job:** Stress-test the plan against its own evidence:
- Are findings properly deduplicated, or is the same issue listed multiple times?
- Do plan items trace back to actual analysis evidence?
- Are effort/risk scores consistent with seam assessments from Phase 6?
- Are dependencies between improvements correctly mapped?
- Do verification methods actually verify the claimed improvements?
- Are there contradictions between analyses and the plan?
- Did the consolidation (Phase 9) drop any important findings?

**Value:** Internal consistency, logical gaps, lost findings, over-optimistic estimates.

## After Both Reviews Complete

The orchestrator:
1. Reads both review outputs
2. Summarizes key critiques from each (brief — don't overwhelm)
3. Writes both reviews to disk
4. Proceeds to Phase 11 where the user sees the draft + both reviews together
