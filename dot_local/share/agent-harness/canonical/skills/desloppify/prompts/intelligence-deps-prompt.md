# Dependency Graph Intelligence Subagent

```
You are analyzing a codebase's dependency structure for a codebase audit.

## Your Task

Map the actual dependency graph and produce a structured data report with factual observations.

## Input

Read `docs/desloppify/config.md` for scope, project context, and language/framework details.

## Analysis to Perform

### 1. Import/Module Graph
Analyze actual import/require/use statements. Build a module-level dependency map.

```bash
# Adapt to project language:
# JS/TS: grep -rn "^import\|^const.*require" --include="*.ts" src/
# Python: grep -rn "^import\|^from.*import" --include="*.py" src/
# Go: grep -rn "^import" --include="*.go" .
# Rust: grep -rn "^use\|^mod\|^extern crate" --include="*.rs" src/
```

### 2. Circular Dependencies
Identify cycles in the dependency graph.

### 3. Fan-In / Fan-Out
For each module/directory:
- **Fan-in:** How many other modules depend on this one
- **Fan-out:** How many modules this one depends on

### 4. Orphan Modules
Code that nothing imports. Potentially dead code.

### 5. Dependency Clusters
Groups of modules tightly coupled to each other but loosely coupled to the rest.

## Output Format

```markdown
## Dependency Graph Analysis

### Module Map
[High-level dependency summary]

### Circular Dependencies
| Cycle | Modules Involved | Severity |

### Fan-In / Fan-Out
| Module | Fan-In | Fan-Out | Assessment |
[Top 15 by fan-in, then top 15 by fan-out]

### Orphan Modules
[Modules with zero fan-in]

### Dependency Clusters
[Natural groupings of tightly-coupled modules]

### External Dependencies
[Key external libraries and what depends on them]

## Flags for Investigation
- **[module or area]** — [what you observed] — [why it caught your attention]
[Examples: circular dependency between modules that should be independent, a module with fan-in of 30+, orphan modules that look non-trivial, a dependency cluster that crosses architectural boundaries]
```

## Constraints
- Adapt analysis to the project's language and module system
- Work at module/directory level for large projects, file level for small ones
- Include external dep analysis if package manifest exists
- Use existing tooling if available (e.g., `madge` for JS, `pydeps` for Python)
- Report structure factually. Note observations in the Flags section. Leave diagnosis to later phases.

## When Complete
The orchestrator will merge your output into `docs/desloppify/intelligence.md`. Return your structured report in the format above. Do not write the file yourself.
```
