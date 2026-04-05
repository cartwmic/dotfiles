# Holistic View Synthesis Subagent

```
You are synthesizing a unified understanding of a codebase from its vertical slices, horizontal slices, and intelligence data.

## Your Task

Combine all enumeration and intelligence data into a holistic view that captures how the codebase fits together.

## Input

Read these artifacts from `docs/desloppify/`:
- `config.md` — Scope and project context
- `intelligence.md` — Git history, dependency graph, static analysis data
- `vertical-slices.md` — All vertical (feature) slices
- `horizontal-slices.md` — All horizontal (cross-cutting) slices

## Analysis to Perform

### 1. Interaction Map
- Where do vertical and horizontal slices intersect?
- Which vertical slices share the most horizontal infrastructure?
- Which horizontal concerns span the most vertical slices?
- Where are boundaries clean vs. blurred?

### 2. Structural Health Signals
- **Coupling hotspots:** Areas where slices are unexpectedly entangled (from intelligence + enumeration data; skip if no git data available)
- **Coverage gaps:** Horizontal concerns that don't reach all vertical slices they should
- **Consistency patterns:** Where the codebase is consistent vs. fragmented
- **Architectural alignment:** Does the actual structure match documented/intended architecture?

### 3. Codebase Trajectory
- Is the codebase improving, degrading, or stable? (from git history trends if available)
- Which areas are actively evolving vs. stagnant?
- Where is technical debt concentrated?

If git history is unavailable, note this and focus on structural signals only.

## Output Format

```markdown
# Holistic View

## Interaction Map
[Matrix or narrative showing vertical × horizontal intersections]

## Structural Health
### Coupling Hotspots
[Areas of unexpected entanglement — or "No git data available" if applicable]

### Coverage Gaps
[Horizontal concerns missing from vertical slices]

### Consistency Patterns
[Where the codebase is uniform vs. fragmented]

### Architectural Alignment
[Actual vs. intended architecture]

## Codebase Trajectory
[Improving / degrading / stable, by area — or structural assessment only if no git history]

## Technical Debt Concentration
[Where debt is concentrated and why]
```

## Constraints
- This is a synthesis, not an analysis — connect dots between slices, don't evaluate code quality yet (that's Phase 6+)
- If intelligence data has gaps (no git history, no coverage data), acknowledge and work with what's available
- Focus on relationships and structure, not individual code issues
- Keep it concise — this artifact is read by many downstream subagents
```
