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

**Parallelism:** Dispatch multiple subagents concurrently. Group by set — all vertical slice analyses can run in parallel, all horizontal slice analyses can run in parallel. Both sets can also run in parallel with each other.

**Context per subagent:** Each subagent receives:
- The specific slice being analyzed (pasted into the prompt by the orchestrator)
- The full `config.md` (criteria and verification methods; if config lists convention docs, subagent should read those too)
- The `intelligence.md` (for hotspot, coupling, coverage data relevant to this slice)
- The `holistic-view.md` (for cross-referencing)
- The opposite enumeration set (vertical subagents get `horizontal-slices.md` and vice versa)

**Token efficiency note:** For large codebases, consider extracting only the relevant sections of `intelligence.md` per slice (e.g., hotspot data for this slice's files only) rather than passing the full intelligence artifact to every subagent.

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
