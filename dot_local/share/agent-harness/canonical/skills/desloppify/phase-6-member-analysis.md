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

**Context per subagent — ORCHESTRATOR PREPARES, subagent does NOT read artifacts from disk:**

The orchestrator extracts and injects only the relevant context into each subagent's prompt. This is critical for token efficiency — do NOT tell subagents to read full artifact files.

For each subagent, the orchestrator prepares:
1. **Slice description** — paste the full slice entry from the enumeration artifact
2. **Analysis criteria** — paste the criteria section from `config.md` (once, same for all)
3. **Relevant intelligence excerpt** — extract ONLY the rows/entries from `intelligence.md` that mention this slice's files (hotspot entries, coupling pairs, coverage data). Do NOT paste the full intelligence file.
4. **Relevant holistic context** — 2-3 sentences from `holistic-view.md` about where this slice sits in the overall health picture. Do NOT paste the full holistic view.
5. **Opposite enumeration summary** — for a vertical slice, list just the horizontal slice NAMES that touch it (from the enumeration). For a horizontal slice, list just the vertical slice NAMES. Do NOT paste full enumeration files.

The subagent then reads only the **actual source code** for the files listed in the slice description. This is the only disk reading the subagent should do.

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
