# Default Verification Methods

These are the default verification methods included in the desloppify plan output. Users can override or extend at invocation time during Phase 1: Configure.

## Defaults

- **Existing test suite passes** — No regressions from changes
- **New/updated tests for refactored code** — Changed code has test coverage
- **Static analysis / linter passes** — Existing tooling reports clean
- **Type checking passes** — If project uses typed language or type annotations
- **Build succeeds** — Project compiles/builds without errors
- **Manual smoke test of affected features** — If applicable, verify user-facing behavior

## Common Extensions (suggested during configure)

- Benchmark before/after for performance-sensitive changes
- Security scan passes
- API contract tests (if public API changes)
- Integration test suite passes
- Documentation review for public-facing changes
- Code review by human before merge
- Deployment to staging environment
