<!-- authored: in-session -->
# Capability: opsx-review-convergence

## ADDED Requirements

### Requirement: Prose Surface Fidelity

THE discipline's prose surfaces — the orchestrator skill, the apply-mode reference, and the code-review template — SHALL state the ledger-repair recovery obligation (a sealed multi-round Verdict without a round ledger is a provenance defect to repair before archive) and SHALL NOT label review findings in a way that implies cross-reviewer finding matching, so operators reading any surface see the same discipline the specs define.

#### Scenario: Recovery obligation stated on the surfaces
- **WHEN** an operator reads the orchestrator skill or the apply-mode reference
- **THEN** the ledger-repair red flag SHALL be present: a sealed multi-round Verdict with no ledger row is a provenance defect — repair the ledger before archive

#### Scenario: Findings section does not imply convergence matching
- **WHEN** a code-review artifact is authored from the shipped template
- **THEN** its findings section heading SHALL be neutral (`Findings`), not `Convergent findings`, since consolidated counts use the max-across-reviewers rule with no cross-reviewer finding matching

#### Scenario: Surface drift is caught deterministically
- **IF** a future edit removes the recovery red flag or reintroduces a convergence-implying findings heading
- **THEN** the required surface test SHALL fail

---

## Acceptance criterion quality checklist

| AC ID | Testable | Solution-free | Unambiguous | Consistent | Complete |
|---|---|---|---|---|---|
| opsx-review-convergence.prose-surface-fidelity | [x] | [x] | [x] | [x] | [x] |
