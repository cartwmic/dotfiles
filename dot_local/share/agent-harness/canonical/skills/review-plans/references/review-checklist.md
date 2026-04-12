# Review Checklist

Use this checklist while auditing plans. Apply only sections that match the plan type, then run the adversarial pressure-test section.

## 1) Requirement Coverage

- Goal is explicit and testable
- In-scope and out-of-scope boundaries are explicit
- External constraints are listed (platform, architecture, policy, tooling)
- Dependencies and assumptions are named

## 2) Design Plan Quality (brainstorming-style)

- Problem statement is concrete (not generic)
- At least one alternative approach is evaluated
- Final approach is justified with tradeoffs
- Failure modes and edge cases are identified
- Data/lifecycle/state transitions are clear where relevant
- Rollout and rollback strategy exists

## 3) Implementation Plan Quality (writing-plans-style)

- Work is split into ordered, executable tasks
- Every task includes exact file paths to create/modify
- Commands are concrete and runnable
- Test-first behavior is explicit where expected
- Verification steps include expected outcomes
- Task dependencies are valid (no impossible ordering)
- Risky or irreversible actions include safeguards

## 4) Verification Depth

- Unit/integration/e2e scope is appropriate for risk
- Negative-path and edge-case tests are included
- Regressions are explicitly checked
- Build/test commands align with repo rules
- Success criteria are measurable and binary

## 5) Operability and Recovery

- Logging/observability implications are covered
- Runtime config or migration impacts are documented
- Rollback path is explicit and feasible
- Stop conditions and escalation points are clear

## 6) Handoff Readiness

- Another engineer could execute without hidden context
- Acronyms and domain terms are not ambiguous
- Open questions are explicit, not buried
- Plan states what "done" means

## 7) Adversarial Pressure Test

- List top assumptions and explain what breaks if each is wrong
- Challenge each major design choice with at least one realistic alternative
- Challenge implementation specifics (data structures, algorithms, sequencing, APIs)
- Probe failure paths: partial rollout, invalid state, retries, cancellation, resource limits
- Identify where the plan is overconfident and request proof (measurements, constraints, prior art)
- Require explicit mitigation or stop-gate for high-uncertainty decisions

## Common Failure Patterns

- Pseudo-steps with no commands or file targets
- "Add validation" style instructions without behavior details
- Missing rollback or recovery for risky changes
- Verification says "run tests" without naming test scope
- Design rationale omitted, forcing re-decision during execution
- Hidden assumptions accepted without challenge
- Default design picked without comparing alternatives
