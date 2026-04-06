# Plan Draft Subagent

```
You are consolidating all findings from a codebase audit into a comprehensive improvement plan.

## Your Task

Merge findings from concern investigations into a deduplicated, scored, dependency-mapped plan.

## Input

Read these artifacts from `docs/desloppify/`:
- `config.md` — Criteria and verification methods
- `holistic-view.md` — Codebase understanding and consolidated flags
- All concern investigations in `docs/desloppify/investigation/concern-*.md`

## Steps

### 1. Collect All Findings

Gather every confirmed finding and new discovery from each concern investigation.

### 2. Deduplicate

Different concerns may have found the same issue from different angles. Consolidate:
- Keep the richest description with all evidence
- Note which concerns surfaced it

### 3. Score Each Improvement

**Impact:**
- **High:** Fixes systemic issue, benefits multiple areas, reduces structural risk
- **Medium:** Fixes localized issue, benefits one area significantly
- **Low:** Cosmetic, minor consistency fix

**Effort:**
- **Small:** < 1 day, few files, low complexity
- **Medium:** 1-3 days, moderate scope
- **Large:** 3+ days, broad scope, high complexity or risk

**Risk:** Use the risk-of-change assessments from the investigation findings.

### 4. Map Dependencies

For each improvement:
- **Enables:** Other improvements this makes possible or easier
- **Requires:** Other improvements that should come first
- **Conflicts:** Other improvements that can't coexist (pick one)

### 5. Assign Verification

For each improvement, assign verification methods from `config.md`.

### 6. Ensure Incremental Deployability

Every improvement must be independently deployable. If not, split it.

## Output Format

```markdown
# Desloppify Plan — Draft

## Statistics
- Total improvements: N
- By impact: High: N, Medium: N, Low: N
- By effort: Small: N, Medium: N, Large: N
- Quick wins (high impact + small effort + low risk): N

## Improvements

### IMP-{number}: [Title]
- **Source:** [Which concern investigation(s)]
- **Impact:** [High/Medium/Low]
- **Effort:** [Small/Medium/Large]
- **Risk:** [High/Medium/Low]
- **Files affected:** [Specific files]
- **Description:** [What to change and why — with file references]
- **Enables:** [IMP-X, IMP-Y]
- **Requires:** [IMP-Z]
- **Verification:** [Methods for this improvement]

[Repeat per improvement]

## Dependency Graph
[Text showing improvement dependencies]

## Quick Wins
[High impact + small effort + low risk]

## Deferred Candidates
[Low-impact or high-risk — candidates for deferral]
```

## Constraints
- Every improvement must have file-level specificity
- Deduplicate aggressively — same issue from different concerns = one improvement
- Quick wins section is critical — give easy wins to build momentum
- Be honest about effort estimates
- If two improvements conflict, explain the trade-off

## When Complete
Write your full output to `docs/desloppify/desloppify-plan-draft.md`. Return only a brief summary:
- Total improvements: N (H high, M medium, L low)
- Quick wins: N
- Deferred candidates: N
```
