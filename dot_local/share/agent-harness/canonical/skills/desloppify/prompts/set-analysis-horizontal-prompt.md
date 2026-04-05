# Horizontal Set Analysis Subagent

```
You are analyzing all horizontal slices as a set to find patterns only visible at the set level.

## Your Task

Identify systemic patterns, set-level coupling, and cross-set insights across all horizontal slices.

## Input

Read these artifacts from `docs/desloppify/`:
- `config.md` — Analysis criteria
- `holistic-view.md` — Unified codebase understanding
- All Phase 6 horizontal analyses: `docs/desloppify/analysis/horizontal-*.md`
- `vertical-slices.md` — Vertical slice enumeration
- Phase 6 vertical analysis summaries: read only the **Summary** section from each `docs/desloppify/analysis/vertical-*.md` (not full text — keep context lean)

## Analysis to Perform

### 1. Systemic Patterns
Look across all per-member analyses for:
- **Repeated findings:** Same issue in 3+ horizontal slices = systemic, not isolated
- **Consistent strengths:** Patterns done well across most concerns (preserve these)
- **Gradients:** Are some cross-cutting concerns well-implemented while others are neglected?
- **Outliers:** Concerns significantly better or worse than the norm — why?

### 2. Set-Level Coupling
- Which horizontal concerns are most entangled with each other?
- Are there natural groupings (e.g., "observability" = logging + metrics + tracing)?
- Should any concerns be merged or split?

### 3. Cross-Set Analysis
- Do all vertical slices use horizontal concerns the same way?
- Which horizontal concerns are well-adopted vs. patchily applied?
- Where do horizontal layer boundaries conflict with vertical feature boundaries?

### 4. Convention Conformance (Set Level)
- Does the set follow stated project conventions consistently?
- Are there informal conventions most concerns follow but some don't?
- Should informal patterns be formalized?

## Output Format

```markdown
# Set Analysis: Horizontal Slices

## Systemic Patterns

### [Pattern Name]
- **Type:** Repeated finding / Consistent strength / Gradient / Outlier
- **Affected members:** [Which slices — with references to their Phase 6 analyses]
- **Evidence:** [Specific examples from per-member analyses]
- **Impact:** [Why this matters at the set level]
- **Suggested improvement:** [Set-level fix, not per-member band-aids]

[Repeat per pattern]

## Set-Level Coupling
[How members relate to each other — groupings, entanglements, merge/split candidates]

## Cross-Set Analysis
[How horizontal concerns map onto vertical slices]

## Convention Conformance
- **Followed consistently:** [Conventions all concerns respect]
- **Followed inconsistently:** [Conventions some concerns break, with specifics]
- **Informal patterns to formalize:** [Patterns worth codifying]

## Summary
- Systemic patterns found: N
- Consistent strengths to preserve: [List]
- Set health assessment: [Strong/Mixed/Weak]
- Top 3 set-level improvements: [Highest-impact items]
```

## Constraints
- Focus on SET-LEVEL insights — don't repeat per-member findings
- Every pattern must cite evidence from at least 2 member analyses
- Read vertical analysis summaries only (Summary section) — not full text
- Distinguish between "inconsistent" and "wrong" — inconsistency is only bad if consistency would be better
```
