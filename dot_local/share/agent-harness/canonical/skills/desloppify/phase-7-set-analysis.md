# Phase 7: Analyze Each Set as a Whole

**Mode:** Subagent (one per set — can run in parallel)

**Reads:** All prior artifacts, especially Phase 6 per-member analyses

**Produces:** `docs/desloppify/set-analysis-vertical.md`, `docs/desloppify/set-analysis-horizontal.md`

## Overview

Analyze patterns that only emerge at the set level — things you can't see by looking at individual slices. Two subagents: one for the vertical set, one for the horizontal set.

## Dispatch

Use separate prompt files per set:
- Vertical set: `./prompts/set-analysis-vertical-prompt.md`
- Horizontal set: `./prompts/set-analysis-horizontal-prompt.md`

**Context per subagent:**
- All Phase 6 analyses for its own set (full text)
- The other set's Phase 6 analysis **summaries only** (Summary section from each file — not full text)
- The other set's enumeration
- `holistic-view.md`
- `config.md` (criteria)

Subagents read these artifacts from disk.

## What Each Subagent Analyzes

### Systemic Patterns
- Issues that appear across multiple members of the set (e.g., "3 of 5 vertical slices handle errors completely differently")
- Patterns that are consistently good (reinforce these, don't break them)
- Gradients — is one end of the codebase cleaner than the other? Why?

### Set-Level Coupling
- Which members of this set are most entangled with each other?
- Are there natural groupings within the set?
- Could some members be merged or split?

### Cross-Set Analysis
- How does this set's health map onto the other set?
- Are horizontal concerns consistently applied across vertical slices? (or vice versa)
- Where do set boundaries conflict?

### Convention Conformance (Set Level)
- Does the set as a whole follow stated project conventions?
- Are there informal conventions that most members follow but some don't?
- Should any informal patterns be formalized?

## Output Format

```markdown
# Set Analysis: [Vertical/Horizontal] Slices

## Systemic Patterns

### [Pattern Name]
- **Affected members:** [Which slices]
- **Description:** [What the pattern is]
- **Impact:** [Why this matters at the set level]
- **Suggested improvement:** [Set-level fix, not per-member]

[Repeat per pattern]

## Set-Level Coupling
[Analysis of how members relate to each other]

## Cross-Set Analysis
[How this set maps onto the other set]

## Convention Conformance
- **Followed consistently:** [Conventions all members respect]
- **Followed inconsistently:** [Conventions some members break]
- **Informal patterns to formalize:** [Patterns worth codifying]

## Summary
- Systemic patterns found: N
- Set health: [Assessment]
- Highest-impact set-level improvements: [Top 3]
```
