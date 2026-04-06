# Phase 7: Consolidate Plan Draft

**Mode:** Subagent-only

**Reads:** All prior artifacts, especially `docs/desloppify/investigation/concern-*.md`

**Produces:** `docs/desloppify/desloppify-plan-draft.md`

## Overview

Merge all findings from Phase 6 investigations into a comprehensive, prioritized, actionable improvement plan draft. This draft goes through adversarial review (Phase 8) before the user finalizes it (Phase 9).

## Dispatch

Use `./prompts/plan-draft-prompt.md`.

The subagent reads the investigation outputs and consolidates them into a scored, dependency-mapped plan.

## After Subagent Completes

The orchestrator verifies the artifact was written to disk, then proceeds to Phase 8 (Adversarial Review).

Do not present the draft to the user yet — the adversarial reviews will improve it first.
