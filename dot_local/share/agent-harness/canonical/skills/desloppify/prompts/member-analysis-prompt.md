# Member Analysis Subagent

```
You are analyzing a single slice of a codebase as part of a systematic audit.

## Your Task

Analyze the slice described below against the configured criteria, cross-referencing the holistic view and both enumeration sets.

## Input

All context is provided below by the orchestrator. **Do NOT read artifact files from `docs/desloppify/`** — everything you need is in this prompt.

**Slice to analyze:**
[ORCHESTRATOR: Paste the full slice entry from the enumeration artifact]

**Analysis criteria:**
[ORCHESTRATOR: Paste the criteria section from config.md]

**Intelligence excerpt (this slice only):**
[ORCHESTRATOR: Paste only the hotspot entries, coupling pairs, and coverage data relevant to this slice's files]

**Holistic context (this slice only):**
[ORCHESTRATOR: 2-3 sentences from holistic-view.md about where this slice fits]

**Related slices from the opposite set:**
[ORCHESTRATOR: List the names of horizontal slices this vertical touches, or vice versa]

**Read the actual source code** for the files listed in the slice description. This is the only disk reading you should do.

## Analysis to Perform

### 1. Apply Each Analysis Criterion

For each criterion in `config.md`, evaluate this slice's code. For each finding:
- What the issue is (specific file and line references)
- Which criterion it violates
- Severity: High / Medium / Low
- Is this isolated to this slice or part of a systemic pattern? (check holistic view)

**Be specific.** "Error handling is inconsistent" is not a finding. "In `src/auth/login.ts:45`, the catch block swallows the error silently while `src/auth/register.ts:67` properly logs and rethrows" IS a finding.

### 2. Seam Identification

For this slice, identify:
- **Existing test coverage:** What tests exist? What critical paths are untested?
- **Clean interfaces:** Where are the natural boundaries? What has clear API contracts?
- **Safe insertion points:** Where could you add tests before refactoring?
- **Risk profile:** How dangerous is changing this slice? Consider: coupling (from dependency data), test coverage (from static analysis), complexity (from hotspot data), fan-in (how many things depend on this)

### 3. Cross-Reference Analysis

- Which horizontal slices does this vertical slice depend on (or vice versa)?
- Are there improvements here that would benefit other slices?
- Are there issues here that originate in other slices?
- Does the holistic view reveal context for why this slice is the way it is?

## Output Format

```markdown
# Analysis: [Slice Name] ([Vertical or Horizontal])

## Findings

### [Finding Title]
- **Criterion:** [Which analysis criterion from config]
- **Severity:** High / Medium / Low
- **Location:** [file:line-range]
- **Description:** [Specific issue with evidence]
- **Holistic context:** [Isolated or systemic?]
- **Suggested improvement:** [Concrete, actionable suggestion]

[Repeat per finding — aim for thoroughness]

## Seam Assessment
- **Test coverage:** [Specific: which files/functions are tested, which aren't]
- **Clean interfaces:** [Where boundaries are well-defined]
- **Safe insertion points:** [Where tests can be added before refactoring]
- **Risk profile:** [High/Medium/Low with reasoning]

## Cross-References
- **Benefits other slices:** [Improvements here that help elsewhere]
- **Caused by other slices:** [Issues rooted in other slices]
- **Shared concerns:** [Patterns relevant to set-level analysis]

## Summary
- Total findings: N (H high, M medium, L low)
- Risk profile: [High/Medium/Low]
- Quick wins: [Low-effort, high-impact items]
- Highest-priority item: [The single most important thing to fix]
```

## Constraints
- Read the actual source code, not just the enumeration description
- Every finding must have file:line references
- Don't list issues you're not confident about — flag uncertainty explicitly
- Keep findings actionable — "this is bad" without a suggestion is not useful
- If a slice has no findings, say so and explain why (either it's genuinely clean or your analysis may be incomplete)

## When Complete
Write your full output to the artifact file (the orchestrator will tell you the path, e.g. `docs/desloppify/analysis/vertical-auth.md`). Return only a brief summary to the orchestrator:
- Slice name and type
- Total findings: N (H high, M medium, L low)
- Risk profile: High/Medium/Low
- Top finding (one sentence)
- Any blockers or issues encountered
```
