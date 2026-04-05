# Phase 6: Analyze Each Member Per Set

**Mode:** Parallel subagents (one per slice)

**Reads:** All prior artifacts in `docs/desloppify/`

**Produces:** `docs/desloppify/analysis/vertical-<slice-name>.md` and `docs/desloppify/analysis/horizontal-<slice-name>.md` per slice

## Overview

Analyze each individual slice against the configured criteria, cross-referencing vertical views, horizontal views, and the holistic view. This is the most parallelizable phase — dispatch one subagent per slice.

## Setup

```bash
mkdir -p docs/desloppify/analysis
```

## Dispatch Strategy

For each slice (vertical and horizontal), dispatch a subagent using `./prompts/member-analysis-prompt.md`.

**Before dispatching:** The orchestrator must prepare each prompt by pasting the specific slice entry from the enumeration artifact into the `[ORCHESTRATOR: ...]` placeholder in the prompt template. Each subagent gets a customized copy of the prompt with its slice description filled in.

**Parallelism:** Dispatch subagents in batches of **3 at a time** (configurable — ask the user during Phase 1 or before Phase 6 dispatch). Do not dispatch all slices simultaneously. Wait for a batch to complete before dispatching the next.

**Model selection:** Phase 6 is the highest-volume, most mechanical phase — subagents apply criteria checklists to code and list findings. A **cheaper/faster model** is appropriate here (e.g., Sonnet-class instead of Opus-class, GPT-4o-mini instead of GPT-4o). Ask the user which model to use for Phase 6 subagents before dispatching. Reserve stronger models for Phases 8 and 10 where judgment matters most.

**Context per subagent:** The orchestrator prepares the prompt by pasting the slice description, then the subagent reads artifacts from disk:
- The specific slice being analyzed (pasted into the prompt by the orchestrator)
- `config.md` — analysis criteria (subagent reads from disk)
- `intelligence.md` — hotspot, coupling, coverage data (subagent reads from disk)
- `holistic-view.md` — cross-referencing (subagent reads from disk)
- The opposite enumeration set — vertical subagents get `horizontal-slices.md` and vice versa (subagent reads from disk)
- If config lists convention docs (AGENTS.md, etc.), subagent should read those too
- The actual source code for files listed in the slice description

Subagents need the full artifacts to do meaningful cross-reference analysis. The throttled batch size (not context starvation) is what controls cost.

## What Each Subagent Analyzes

### Against Configured Criteria
Apply each criterion from `config.md` to this slice's code. For each finding:
- What the issue is (specific, with file/line references)
- Which criterion it violates
- Severity: High / Medium / Low
- How it relates to the holistic view (isolated issue or systemic pattern?)

### Seam Identification
For each slice, identify:
- **Existing test coverage** — What's tested? What's not?
- **Clean interfaces** — Where are the natural boundaries for safe changes?
- **Safe insertion points** — Where can tests be added before refactoring?
- **Risk profile** — How dangerous is it to change this slice? (based on coupling, test coverage, complexity)

### Cross-Reference Analysis
- How does this slice interact with the horizontal/vertical slices it touches?
- Are there improvements in this slice that would benefit other slices?
- Are there issues in this slice caused by problems in other slices?

## Output Format

Each subagent writes its analysis:

```markdown
# Analysis: [Slice Name] ([Vertical/Horizontal])

## Findings

### [Finding Title]
- **Criterion:** [Which analysis criterion]
- **Severity:** [High/Medium/Low]
- **Location:** [File(s) and line ranges]
- **Description:** [What's wrong]
- **Holistic context:** [How this relates to broader codebase health]
- **Suggested improvement:** [Concrete suggestion]

[Repeat per finding]

## Seam Assessment
- **Test coverage:** [Good/Partial/None — specifics]
- **Clean interfaces:** [Where boundaries are clear]
- **Safe insertion points:** [Where to add tests]
- **Risk profile:** [High/Medium/Low — reasoning]

## Cross-References
- **Benefits other slices:** [Improvements here that help elsewhere]
- **Caused by other slices:** [Issues here rooted elsewhere]
- **Shared concerns:** [Patterns seen across multiple slices]

## Summary
- Total findings: N (H high, M medium, L low)
- Risk profile: [High/Medium/Low]
- Quick wins: [Low-effort, high-impact items]
```

## After All Subagents Complete

Orchestrator briefly reviews outputs for completeness, then presents a summary to the user:
- Total findings per slice
- Distribution of severity
- Any slices that had no findings (suspicious — might mean subagent missed things)
- Top quick wins across all slices

Ask: "Any slices you expected more findings in? Should I re-analyze any?"
