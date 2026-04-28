# Phase 6: Triage + Investigate Concerns

**Mode:** Hybrid (orchestrator triage → user validation → 3-5 investigation subagents)

**Reads:** All prior artifacts, especially `docs/desloppify/holistic-view.md` (which contains consolidated flags)

**Produces:** `docs/desloppify/investigation/concern-*.md` (one per concern)

## Overview

Collect all flags from Phases 2-5, group them into 3-5 concern themes, validate with the user, then dispatch focused investigation subagents — one per concern. Each subagent reads only the source files relevant to its concern and produces confirmed findings with file:line references.

## Step 1: Collect and Group Flags

Read the "Consolidated Flags for Investigation" section from `holistic-view.md`. Group flags into concern themes by clustering related observations.

Example groupings:
- "FFI boundary complexity" — flags about bridge files, DTO duplication, error flattening
- "Test coverage gaps in critical paths" — flags about untested high-fan-in modules
- "Code duplication patterns" — flags about repeated logic across files
- "Dead code and decay" — flags about orphan modules, stale files, unused exports
- "Architectural drift" — flags about layer violations, convention inconsistencies

Target **3-5 concerns**. Each concern should:
- Have a clear investigation question (what to confirm or dismiss)
- Reference specific files to read
- Group 3-10 related flags

## Step 2: Present Concerns to User (Socratic)

Present each concern with its flags and investigation question:

"Based on the flags from Phases 2-5, I've grouped observations into N concerns. For each one, I'll dispatch an investigation subagent to read the actual code and confirm or dismiss the flags."

Walk through each concern one at a time:
- "Concern 1: [name]. These flags suggest [summary]. The investigation would read [files]. Does this concern make sense? Want to adjust scope?"
- "Any concerns I'm missing? Anything from your experience that the flags didn't capture?"

The user may:
- Adjust concern scope (add/remove files, refine the question)
- Add entirely new concerns from domain knowledge
- Remove concerns they already know about or don't care about
- Reprioritize which concerns matter most

## Step 3: Set Up Investigation Directory

```bash
mkdir -p docs/desloppify/investigation
```

## Step 4: Dispatch Investigation Subagents

Use `./prompts/investigate-concern-prompt.md` for each concern.

**Use the analytical-tier model** for investigation subagents.

**Dispatch in batches** per the configured batch size (default 3). Wait for a batch to complete before dispatching the next.

**Each subagent receives (injected into prompt by orchestrator):**
1. The concern name and investigation question
2. The specific flags being investigated
3. The list of files to read
4. The analysis criteria from `config.md`
5. Brief holistic context (2-3 sentences about where this concern fits)

**Each subagent reads from disk:**
- Only the source code files listed for its concern

**Subagent success verification:** After each batch, check for artifact files on disk. A subagent that wrote its artifact is successful regardless of what it returned to the orchestrator.

## Step 5: Review and Present Results

After all investigation subagents complete:

1. Read each `investigation/concern-*.md` file
2. Present a summary to the user:
   - Findings per concern (confirmed flags, dismissed flags, new discoveries)
   - Severity distribution
   - Quick wins identified
3. Ask: "Any concerns where the investigation missed something? Should I dig deeper anywhere?"

## Output

Each subagent writes `docs/desloppify/investigation/concern-<name>.md` following the format in the investigation prompt.
