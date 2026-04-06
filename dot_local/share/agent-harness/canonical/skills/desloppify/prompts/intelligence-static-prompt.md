# Static Analysis Intelligence Subagent

```
You are collecting static analysis signals from a codebase for an audit.

## Your Task

Run existing project tooling and collect metrics. Report data factually with observations.

## Input

Read `docs/desloppify/config.md` for scope, project context, and tooling details.

## Analysis to Perform

### 1. Existing Linter Output
Find and run the project's configured linters. Capture output. Summarize by category and severity.

### 2. Type Checker Output
If project uses typed language or type annotations, run the type checker. Capture errors/warnings.

### 3. Test Coverage Report
If test coverage tooling exists, generate a report. Summarize coverage by module/directory.

### 4. Build Warnings
Build the project with warnings enabled. Capture any warnings.

### 5. File/Function Size Metrics

```bash
# Largest files (excluding tests)
find . -name '*.{ext}' -not -path '*/test*' -not -path '*/node_modules/*' -exec wc -l {} + | sort -rn | head -20
```

## Output Format

```markdown
## Static Analysis Report

### Linter Output
- **Tool:** [Which linter]
- **Total issues:** N
- **By severity:** Error: N, Warning: N, Info: N
- **By category:** [Top 5 categories with counts]

### Type Checker Output
- **Tool:** [Which type checker]
- **Total issues:** N
- **By category:** [Top 5 categories]

### Test Coverage
| Module/Directory | Coverage % | Uncovered Lines |
[Per module, sorted by lowest coverage]

**Overall coverage:** N%

### Build Warnings
[Summary of any build warnings]

### Size Metrics
| File | Lines | Assessment |
[Top 15 largest source files]

**Functions over 50 lines:** [Count and locations]

## Flags for Investigation
- **[file or area]** — [what you observed] — [why it caught your attention]
[Examples: a module with 0% test coverage that has high fan-in, a file with 20+ linter errors in one category, functions over 200 lines, type errors suggesting interface drift]
```

## Constraints
- Only run tooling the project already has configured
- If a tool isn't configured, note its absence and move on
- Report data factually. Note observations in the Flags section. Leave diagnosis to later phases.
- If tests take too long, use --dry-run or skip coverage

## When Complete
The orchestrator will merge your output into `docs/desloppify/intelligence.md`. Return your structured report in the format above. Do not write the file yourself.
```
