# Dependency Graph Intelligence Subagent

```
You are analyzing a codebase's dependency structure for a codebase audit.

## Your Task

Map the actual dependency graph of this project and produce a structured report.

## Input

Read `docs/desloppify/config.md` for scope, project context, and language/framework details.

## Analysis to Perform

### 1. Import/Module Graph
Analyze actual import/require/use statements to map dependencies:

```bash
# Adapt to project language:
# JavaScript/TypeScript
grep -rn "^import\|^const.*require" --include="*.ts" --include="*.js" --include="*.tsx" --include="*.jsx" src/

# Python
grep -rn "^import\|^from.*import" --include="*.py" src/

# Go
grep -rn "^import" --include="*.go" .

# Rust
grep -rn "^use\|^mod\|^extern crate" --include="*.rs" src/
```

Build a module-level dependency map (not file-level unless project is small).

### 2. Circular Dependencies
Identify cycles in the dependency graph. Trace import chains that loop back.

### 3. Fan-In / Fan-Out
For each module/directory:
- **Fan-in:** How many other modules depend on this one
- **Fan-out:** How many modules this one depends on

High fan-in = widely depended upon (changes are risky).
High fan-out = depends on everything (fragile, hard to test).

### 4. Orphan Modules
Code that nothing imports. Potentially dead code.

### 5. Dependency Clusters
Groups of modules that are tightly coupled to each other but loosely coupled to the rest. These are natural boundaries.

## Output Format

```markdown
## Dependency Graph Analysis

### Module Map
[High-level dependency summary — which modules depend on which]

### Circular Dependencies
| Cycle | Modules Involved | Severity |
|-------|-----------------|----------|
[Any cycles found]

### Fan-In / Fan-Out
| Module | Fan-In | Fan-Out | Assessment |
|--------|--------|---------|------------|
[Top 15 by fan-in, then top 15 by fan-out]

### Orphan Modules
[Modules with zero fan-in — potentially dead code]

### Dependency Clusters
[Natural groupings of tightly-coupled modules]

### External Dependencies
[Key external libraries/frameworks and what depends on them]
```

## Constraints
- Adapt analysis to the project's language and module system
- Work at module/directory level for large projects, file level for small ones
- If project has a package.json, Cargo.toml, go.mod etc., include external dep analysis
- Use existing tooling if available (e.g., `madge` for JS, `pydeps` for Python)
- Report structure, don't judge — analysis comes in later phases
```
