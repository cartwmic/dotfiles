# Plan Draft Subagent

```
You are consolidating all findings from a codebase audit into a comprehensive improvement plan.

## Your Task

Merge findings from all analysis phases into a deduplicated, scored, dependency-mapped plan.

## Input

**Read these artifacts from `docs/desloppify/`:**
- `config.md` — Criteria and verification methods
- Phase 6 per-member analyses: read the **Summary** and **Findings** sections from each file in `docs/desloppify/analysis/` (skip full Seam Assessment details — use the risk profile line only)
- `set-analysis-vertical.md`, `set-analysis-horizontal.md` (full text)
- `holistic-analysis.md` (full text)

## Steps

### 1. Collect All Findings

Gather findings from:
- Per-member analysis summaries and findings (Phase 6)
- Set-level patterns (Phase 7 — full text)
- Holistic improvements (Phase 8 — full text)

### 2. Deduplicate

The same issue often surfaces at multiple levels. Consolidate:
- If a per-member finding is also a systemic pattern, keep it as one improvement referencing both
- If a set-level pattern is also a holistic concern, consolidate at the holistic level
- Preserve the richest description and all relevant evidence

### 3. Score Each Improvement

**Impact** (How much does this improve the codebase?):
- **High:** Fixes systemic issue, benefits multiple slices, reduces structural risk
- **Medium:** Fixes localized issue, benefits one slice significantly
- **Low:** Cosmetic, minor consistency fix

**Effort** (How hard is this change?):
- **Small:** < 1 day, few files, low complexity
- **Medium:** 1-3 days, moderate scope
- **Large:** 3+ days, broad scope, high complexity or risk

**Risk** (What breaks if we get it wrong?):
- **High:** Core path, low test coverage, high coupling (from seam assessments)
- **Medium:** Important path, partial coverage, moderate coupling
- **Low:** Well-tested, clear interfaces, few dependents

### 4. Map Dependencies

For each improvement:
- **Enables:** Other improvements this makes possible or easier
- **Requires:** Other improvements that should come first
- **Conflicts:** Other improvements that can't coexist (pick one)

### 5. Assign Verification

For each improvement, assign verification methods from `config.md`. Add improvement-specific verification if needed.

### 6. Ensure Incremental Deployability

Every improvement MUST be independently deployable:
- Can be merged on its own without breaking the codebase
- Has its own verification that confirms success
- Doesn't leave the codebase in a half-migrated state

If an improvement can't be deployed independently, split it into independently-deployable sub-improvements.

## Output Format

```markdown
# Desloppify Plan — Draft

## Statistics
- Total improvements: N
- By impact: High: N, Medium: N, Low: N
- By effort: Small: N, Medium: N, Large: N
- By risk: High: N, Medium: N, Low: N
- Quick wins (high impact + small effort + low risk): N

## Improvements

### IMP-{number}: [Title]
- **Source:** [Phase 6: slice X / Phase 7: vertical set / Phase 8: holistic]
- **Impact:** [High/Medium/Low]
- **Effort:** [Small/Medium/Large]
- **Risk:** [High/Medium/Low]
- **Slices affected:** [Vertical and/or horizontal slices]
- **Description:** [What to change and why — specific, with file references]
- **Seam assessment:** [Test coverage, clean interfaces, safe insertion points for this change]
- **Enables:** [IMP-X, IMP-Y]
- **Requires:** [IMP-Z]
- **Conflicts:** [IMP-W — choose one]
- **Verification:** [Methods for this specific improvement]
- **Independently deployable:** [Yes / No — if no, list sub-improvements]

[Repeat per improvement]

## Dependency Graph
[Text representation showing improvement dependencies]

## Quick Wins
[Filtered list: High impact + Small effort + Low risk — execute these first]

## Deferred Candidates
[Improvements that are low-impact or high-risk — candidates for deferral]
```

## Constraints
- Every improvement must have file-level specificity (not "improve error handling" but "standardize error handling in src/api/*.ts to use the pattern from src/auth/errors.ts")
- Deduplication must be aggressive — the user shouldn't see the same issue 3 times at different zoom levels
- Quick wins section is critical — give the user easy wins to build momentum
- Be honest about effort estimates — underestimating effort is worse than overestimating
- If two improvements conflict, explain the trade-off clearly

## When Complete
Write your full output to `docs/desloppify/desloppify-plan-draft.md`. Return only a brief summary to the orchestrator:
- Total improvements: N (H high-impact, M medium, L low)
- Quick wins: N
- Deferred candidates: N
- Any blockers or issues encountered
```
