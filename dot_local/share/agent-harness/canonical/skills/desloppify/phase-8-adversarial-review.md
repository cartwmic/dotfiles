# Phase 8: Adversarial Review

**Mode:** Parallel subagents (blind + context-aware)

**Reads:** See per-reviewer details below

**Produces:** `docs/desloppify/review-blind.md`, `docs/desloppify/review-contextual.md`

## Overview

Two independent reviewers challenge the plan draft before the user finalizes it. They run in parallel with deliberately different context levels.

**Use the judgment-tier model** for both reviewers — this is where strong reasoning matters most.

## Why Two Reviewers

- **Blind reviewer** breaks the confirmation chain by looking at code with fresh eyes
- **Context-aware reviewer** stress-tests internal consistency of the analysis chain

## Reviewer 1: Blind Review

**Prompt:** `./prompts/review-blind-prompt.md`

**Gets:** The codebase itself, `desloppify-plan-draft.md`, `config.md`

**Does NOT get:** intelligence, slices, holistic view, investigation outputs

**Job:** Read the code independently. Does the plan target the right problems? What does it miss? Are items unjustified?

## Reviewer 2: Context-Aware Review

**Prompt:** `./prompts/review-contextual-prompt.md`

**Gets:** All artifacts including plan draft

**Job:** Stress-test internal consistency. Are findings deduplicated? Do scores match evidence? Are dependencies correct? Were investigation findings dropped?

## After Both Reviews Complete

Verify both review artifacts exist on disk. A reviewer that wrote its artifact is successful regardless of return status.

Proceed to Phase 9 where the user sees the draft + both reviews together.
