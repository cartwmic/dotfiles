# Static Analysis Intelligence Subagent

```
You are collecting static analysis signals from a codebase for an audit.

## Your Task

Run existing project tooling and collect metrics. Do NOT configure new tools — use what the project already has.

## Input

Read `docs/desloppify/config.md` for scope, project context, and tooling details.

## Analysis to Perform

### 1. Existing Linter Output
Find and run the project's configured linters:

```bash
# Check for common linter configs and run them
# JavaScript/TypeScript: .eslintrc*, biome.json
# Python: pyproject.toml (ruff/flake8/pylint), .flake8
# Go: golangci-lint
# Rust: clippy
```

Capture output. Summarize by category and severity.

### 2. Type Checker Output
If project uses typed language or type annotations:

```bash
# TypeScript: npx tsc --noEmit
# Python: mypy, pyright
# etc.
```

Capture errors/warnings. Summarize by category.

### 3. Test Coverage Report
If test coverage tooling exists, generate a report:

```bash
# Look for existing coverage configs
# JavaScript: jest --coverage, vitest --coverage
# Python: pytest --cov
# Go: go test -cover
```

Summarize coverage by module/directory. Flag uncovered areas.

### 4. Build Warnings
Build the project with warnings enabled. Capture any warnings.

### 5. File/Function Size Metrics

```bash
# Largest files (lines of code, excluding tests)
find . -name '*.{ext}' -not -path '*/test*' -not -path '*/node_modules/*' -exec wc -l {} + | sort -rn | head -20

# Functions/methods over 50 lines (language-dependent heuristic)
```

## Output Format

```markdown
## Static Analysis Report

### Linter Output
- **Tool:** [Which linter]
- **Total issues:** N
- **By severity:** Error: N, Warning: N, Info: N
- **By category:** [Top 5 categories with counts]
- **Notable patterns:** [Recurring issues]

### Type Checker Output
- **Tool:** [Which type checker]
- **Total issues:** N
- **By category:** [Top 5 categories]

### Test Coverage
| Module/Directory | Coverage % | Uncovered Lines |
|-----------------|-----------|----------------|
[Per module, sorted by lowest coverage]

**Overall coverage:** N%
**Critical gaps:** [Important code with no coverage]

### Build Warnings
[Summary of any build warnings]

### Size Metrics
| File | Lines | Assessment |
|------|-------|------------|
[Top 15 largest source files]

**Functions over 50 lines:** [Count and locations]
```

## Constraints
- Only run tooling the project already has configured
- If a tool isn't configured, note its absence and move on
- Don't install new tools or add new configs
- **DATA ONLY — do NOT suggest fixes, improvements, or refactoring actions.** Capture raw numbers and tool output. Interpretation and recommendations happen in later phases, not here.
- If tests take too long, use --dry-run or skip coverage

## When Complete
The orchestrator will merge your output into `docs/desloppify/intelligence.md`. Return your structured report in the format above. Do not write the file yourself.
```
