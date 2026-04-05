# Vertical Set Analysis Subagent

```
You are analyzing all vertical slices as a set to find patterns only visible at the set level.

## Your Task

Identify systemic patterns, set-level coupling, and cross-set insights across all vertical slices.

## Input

Read these artifacts from `docs/desloppify/`:
- `config.md` — Analysis criteria
- `holistic-view.md` — Unified codebase understanding
- All Phase 6 vertical analyses: `docs/desloppify/analysis/vertical-*.md`
- `horizontal-slices.md` — Horizontal slice enumeration
- Phase 6 horizontal analysis summaries: read only the **Summary** section from each `docs/desloppify/analysis/horizontal-*.md` (not full text — keep context lean)

## Analysis to Perform

### 1. Systemic Patterns
Look across all per-member analyses for:
- **Repeated findings:** Same issue in 3+ vertical slices = systemic, not isolated
- **Consistent strengths:** Patterns done well across most slices (preserve these)
- **Gradients:** Is one end of the codebase cleaner than the other? Why?
- **Outliers:** Slices significantly better or worse than the norm — why?

### 2. Set-Level Coupling
- Which vertical slices are most entangled with each other?
- Are there natural sub-groupings?
- Should any slices be merged (awkwardly split) or split (doing too much)?

### 3. Cross-Set Analysis
- Are horizontal concerns consistently applied across all vertical slices?
- Which vertical slices benefit from good horizontal infrastructure vs. which are left out?
- Where do vertical boundaries conflict with horizontal layer boundaries?

### 4. Convention Conformance (Set Level)
- Does the set follow stated project conventions consistently?
- Are there informal conventions most slices follow but some don't?
- Should informal patterns be formalized?

## Output Format

```markdown
# Set Analysis: Vertical Slices

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
[How vertical slice patterns map onto horizontal concerns]

## Convention Conformance
- **Followed consistently:** [Conventions all slices respect]
- **Followed inconsistently:** [Conventions some slices break, with specifics]
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
- Read horizontal analysis summaries only (Summary section) — not full text
- Distinguish between "inconsistent" and "wrong" — inconsistency is only bad if consistency would be better

## When Complete
Write your full output to `docs/desloppify/set-analysis-vertical.md`. Return only a brief summary to the orchestrator:
- Systemic patterns found: N
- Set health: Strong/Mixed/Weak
- Top set-level improvement (one sentence)
- Any blockers or issues encountered
```
