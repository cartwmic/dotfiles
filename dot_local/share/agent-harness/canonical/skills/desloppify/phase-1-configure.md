# Phase 1: Configure

**Mode:** Orchestrator + user (no subagent)

**Reads:** Project docs (AGENTS.md, CLAUDE.md, README, style guides, linter configs, ADRs)

**Produces:** `docs/desloppify/config.md`

## Steps

### 1. Set Up Artifact Directory

```bash
mkdir -p docs/desloppify
```

### 2. Discover Existing Conventions

Scan the project for:
- `AGENTS.md`, `CLAUDE.md`, `CONVENTIONS.md`, or similar
- Linter/formatter configs (`.eslintrc`, `pyproject.toml`, `rustfmt.toml`, etc.)
- Type checker configs (`tsconfig.json`, `mypy.ini`, etc.)
- Architecture Decision Records (`docs/adr/`, `docs/decisions/`)
- README and other project docs
- CI/CD configuration (what's already automated)

Summarize what you found to the user.

### 3. Agree on Analysis Criteria

Present the defaults from `./default-criteria.md` to the user:

"Here are the default analysis criteria I'll use. You can:
- **Remove** any that don't apply to this project
- **Add** custom criteria specific to your concerns
- **Adjust** the focus (e.g., 'prioritize architecture over code quality')"

Ask one question at a time. Explore what the user cares about most.

### 4. Agree on Verification Methods

Present the defaults from `./default-verification.md`:

"Here are the default verification methods for the plan output. Same deal — remove, add, or adjust."

Ask what testing/verification infrastructure the project already has.

### 5. Agree on Execution Settings

Discuss operational settings:

**Model selection:** "Some phases are mechanical (data gathering) and can use a cheaper model. Others need strong reasoning (adversarial review). Want to use different models per tier?"

Suggested model tiers:
- **Mechanical** (Phase 2): cheaper/faster model (e.g., Sonnet, GPT-4o-mini, Gemini Flash)
- **Analytical** (Phases 3-6): default model
- **Judgment** (Phase 8): strongest available model

**Batch size:** "Phase 6 dispatches 3-5 investigation subagents. Phase 2 dispatches 3 intelligence subagents. Any concurrency preferences?"

### 6. Agree on Scope

For large codebases, discuss:
- Should we audit the entire codebase or a subsystem?
- Are there areas to explicitly exclude?
- Any known problem areas to focus on?

### 7. Write Config Artifact

Write `docs/desloppify/config.md`:

```markdown
# Desloppify Configuration

## Scope
[Full codebase / specific subsystem / exclusions]

## Analysis Criteria
[Final agreed criteria — defaults + modifications]

## Verification Methods
[Final agreed methods — defaults + modifications]

## Existing Conventions Discovered
[List of convention docs found, with brief summary of each]

## Project Context
[Key project details: language, framework, build system, test framework, CI]

## Execution Settings
- **Model tiers:**
  - Mechanical (Phase 2): [model name]
  - Analytical (Phases 3-6): [model name]
  - Judgment (Phase 8): [model name]
- **Batch size:** [default 3]
```
