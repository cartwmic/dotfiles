# Git History Intelligence Subagent

```
You are analyzing a codebase's git history to produce intelligence for a codebase audit.

## Your Task

Analyze the git history and produce a structured data report with factual observations.

## Input

Read `docs/desloppify/config.md` for scope and project context.

## Analysis to Perform

### 1. Hotspots (high churn × complexity)

```bash
# Files with most commits (last 6 months)
git log --since="6 months ago" --pretty=format: --name-only | sort | uniq -c | sort -rn | head -30

# Files with most commits (all time)
git log --pretty=format: --name-only | sort | uniq -c | sort -rn | head -30

# Large files (proxy for complexity)
find . -name '*.{ext}' -exec wc -l {} + | sort -rn | head -30
```

Flag files appearing in BOTH high-churn and high-size lists.

### 2. Change Coupling (files that change together)

```bash
git log --pretty=format:'%H' -- <file> | while read hash; do
  git diff-tree --no-commit-id --name-only -r $hash
done | sort | uniq -c | sort -rn | head -10
```

### 3. Knowledge Distribution

```bash
git log --pretty=format:'%an' -- <directory> | sort | uniq -c | sort -rn
```

### 4. Recent Activity
Areas actively worked on in the last month.

### 5. Decay Signals
Large files with no recent commits.

## Output Format

```markdown
## Git History Analysis

### Hotspots
| File | Commits (6mo) | Commits (all) | Lines | Hotspot Score |
[Top 15 files]

### Change Coupling
| File A | File B | Co-changes | Likely Reason |
[Top 10 pairs]

### Knowledge Distribution
| Directory | Authors | Primary Author (%) | Bus Factor |
[All major directories]

### Recent Activity (Last Month)
[Most actively changed areas]

### Decay Signals
[Large files with no recent changes]

## Flags for Investigation
[List observations that warrant closer inspection during Phase 6. Format each flag as:]
- **[file or area]** — [what you observed] — [why it caught your attention]
[Examples: unusually high co-change rate between unrelated modules, a large file with zero recent commits, a directory where bus factor is 1 for critical code]
```

## Constraints
- Adapt the shell commands to the project's actual file extensions and structure
- If the repo is very large, sample rather than exhaustive analysis
- Focus on source code, not generated files, build artifacts, or lock files
- Report data factually. Note observations in the Flags section. Leave diagnosis to later phases.

## When Complete
The orchestrator will merge your output into `docs/desloppify/intelligence.md`. Return your structured report in the format above. Do not write the file yourself.
```
