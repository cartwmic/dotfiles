# Default Analysis Criteria

These are the default criteria applied during analysis phases (6, 7, 8). Users can override or extend at invocation time during Phase 1: Configure.

## Code Quality

- **Code duplication / DRY violations** — Same logic repeated in multiple places
- **Dead code / unused exports** — Code that's never called or imported
- **Inconsistent patterns** — Same thing done different ways across the codebase
- **Overly complex functions/classes** — High cyclomatic complexity, deep nesting, long methods
- **Poor naming / unclear intent** — Names that don't communicate purpose

## Architecture

- **Tight coupling** — Slices that should be independent are entangled
- **Leaky abstractions** — Layer violations, implementation details crossing boundaries
- **Missing abstractions** — Repeated inline logic that should be extracted
- **Circular dependencies** — Modules depending on each other in cycles

## Maintainability

- **Missing or inadequate error handling** — Swallowed errors, generic catches, no recovery
- **Missing or inadequate test coverage** — Untested critical paths, shallow tests
- **Stale or misleading comments/docs** — Comments that contradict the code
- **Magic numbers / hardcoded values** — Unexplained literals scattered through code
- **Configuration scattered vs centralized** — Config values in random locations

## Consistency

- **Mixed conventions** — Formatting, file organization, naming style varies
- **Inconsistent API contracts** — Similar components with different interfaces
- **Inconsistent error handling strategies** — Different error patterns per module

## Convention Conformance

- **Stated vs actual** — Does the code follow its own AGENTS.md, style guides, linter configs, ADRs?
- **Linter/type-checker violations** — Existing tooling already flags issues
- **Architectural drift** — Code no longer matches documented architecture
