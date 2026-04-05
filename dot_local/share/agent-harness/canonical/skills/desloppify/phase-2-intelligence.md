# Phase 2: Gather Project Intelligence

**Mode:** Parallel subagents (up to 3)

**Reads:** `docs/desloppify/config.md`

**Produces:** `docs/desloppify/intelligence.md`

## Overview

Automated data gathering that feeds all subsequent phases. Dispatch up to three parallel subagents, then merge their outputs into a single intelligence artifact.

## Subagents to Dispatch

### 1. Git History Analysis
**Prompt:** `./prompts/intelligence-git-prompt.md`

Analyzes:
- **Hotspots** — Files with highest churn (commit frequency × file size/complexity)
- **Change coupling** — Files that frequently change together (hidden dependencies)
- **Knowledge distribution** — How many unique authors per file/directory (bus factor)
- **Recent activity** — What areas are actively being worked on
- **Decay signals** — Large files that haven't been touched in a long time

### 2. Dependency Graph Analysis
**Prompt:** `./prompts/intelligence-deps-prompt.md`

Analyzes:
- **Import/module graph** — Actual dependency relationships
- **Circular dependencies** — Cycles in the dependency graph
- **Fan-in/fan-out** — Modules with many dependents (high fan-in) or many dependencies (high fan-out)
- **Orphan modules** — Code that nothing imports
- **Dependency clusters** — Groups of tightly coupled modules

### 3. Static Analysis Scan
**Prompt:** `./prompts/intelligence-static-prompt.md`

Collects:
- **Existing linter output** — Run project's configured linters
- **Type checker output** — Run project's type checker if present
- **Test coverage report** — Generate if tooling exists
- **Build warnings** — Compile/build with warnings enabled
- **File/function size metrics** — Identify oversized files and functions

## Merging Outputs

After all subagents complete, merge their outputs into `docs/desloppify/intelligence.md`:

```markdown
# Project Intelligence

## Git History Analysis
[Subagent 1 output]

## Dependency Graph
[Subagent 2 output]

## Static Analysis
[Subagent 3 output]

## Key Signals
[Orchestrator summary: top hotspots, critical coupling, major gaps]
```

Present the Key Signals summary to the user before proceeding. Ask: "Anything surprising here? Anything you expected to see that's missing?"

## Graceful Degradation

Not all intelligence sources will be available for every project. Handle missing data explicitly:

| Missing Data | Impact | Handling |
|---|---|---|
| **No git history** (new repo, shallow clone) | No hotspots, coupling, knowledge distribution, trajectory | Mark these as "Unavailable" in intelligence.md. Downstream phases skip hotspot-based prioritization and focus on structural analysis only. |
| **No tests / no coverage tooling** | No coverage data | Seam assessments in Phase 6 note "No test coverage data available." Every slice gets elevated risk profile by default. |
| **No linter configured** | No lint output | Convention conformance relies on manual analysis only. Note absence in intelligence.md. |
| **Single developer** | Bus factor = 1 everywhere | Note once in intelligence.md as project context, not as a per-directory risk. Suppress repetitive bus-factor warnings in downstream phases. |
| **Library / infrastructure codebase** | App-centric entry points don't apply | Intelligence subagents adapt: exports are entry points for libraries, resources/modules for infrastructure. Note project type in Key Signals. |
