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

Discuss operational settings for the subagent-heavy phases:

**Batch size:** "Phase 6 dispatches one subagent per slice (you have N slices). How many should run concurrently? Default is 3."

**Model selection:** "Some phases are mechanical (data gathering, checklist analysis) and can use a cheaper model. Others need strong reasoning (architectural assessment, adversarial review). Want to use a cheaper model for the mechanical phases?"

Suggested model tiers:
- **Mechanical** (Phases 2, 6): cheaper/faster model (e.g., Sonnet, GPT-4o-mini, Gemini Flash)
- **Analytical** (Phases 3-5, 7, 9, 12): default model
- **Judgment** (Phases 8, 10): strongest available model

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
- **Batch size:** [N concurrent subagents for Phase 6, default 3]
- **Model tiers:**
  - Mechanical (Phases 2, 6): [model name]
  - Analytical (Phases 3-5, 7, 9, 12): [model name]
  - Judgment (Phases 8, 10): [model name]
```
