# Phase 2: Gather Project Intelligence

**Mode:** Parallel subagents (up to 3)

**Reads:** `docs/desloppify/config.md`

**Produces:** `docs/desloppify/intelligence.md`

**Model selection:** Intelligence gathering is mechanical — run commands, format output. Use the mechanical-tier model.

## Overview

Automated data gathering that feeds all subsequent phases. Dispatch up to three parallel subagents, then merge their outputs into a single intelligence artifact.

## Subagents to Dispatch

### 1. Git History Analysis
**Prompt:** `./prompts/intelligence-git-prompt.md`

Analyzes: hotspots, change coupling, knowledge distribution, recent activity, decay signals.

### 2. Dependency Graph Analysis
**Prompt:** `./prompts/intelligence-deps-prompt.md`

Analyzes: import/module graph, circular dependencies, fan-in/fan-out, orphan modules, dependency clusters.

### 3. Static Analysis Scan
**Prompt:** `./prompts/intelligence-static-prompt.md`

Collects: linter output, type checker output, test coverage, build warnings, file/function size metrics.

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
[Top 5 hotspots by churn, strongest coupling pairs, notable coverage gaps — data only]

## Flags for Investigation
[Merge all flags from the three subagents into one list]
```

Present the Key Signals summary to the user before proceeding. Keep this factual — present data, not conclusions.

Ask: "Anything surprising here? Anything you expected to see that's missing?"

## Subagent Success Verification

After each subagent completes, verify success by checking artifact output quality. If a subagent returns empty or malformed output, retry once before proceeding.

## Graceful Degradation

| Missing Data | Handling |
|---|---|
| **No git history** | Mark as "Unavailable." Downstream phases skip hotspot-based prioritization. |
| **No tests / no coverage tooling** | Note absence. Every area gets elevated risk profile by default. |
| **No linter configured** | Note absence. Convention conformance relies on manual analysis only. |
| **Single developer** | Note once as project context. Suppress repetitive bus-factor warnings. |
| **Library / infrastructure codebase** | Adapt: exports are entry points for libraries, resources for infrastructure. |
