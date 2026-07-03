<!-- authored: in-session -->
# Capability: opsx-post-impl-review

## ADDED Requirements

### Requirement: Verdict Under The Severity Floor

THE code-review.md `Verdict` SHALL be `pass` if and only if no P0 or P1 finding remains open under the opsx-review-convergence baseline-bounded contract, and open P2/P3 findings SHALL be recorded in the artifact as warnings without blocking the verdict, the gate, or archive.

#### Scenario: Advisory-only residue passes
- **WHEN** the final review round leaves only P2/P3 findings open
- **THEN** code-review.md SHALL record `Verdict: pass` and list the open P2/P3 findings as warnings

#### Scenario: Open blocker fails
- **WHILE** a P0 or P1 finding is open
- **THEN** code-review.md SHALL NOT record `Verdict: pass`

### Requirement: Round Ledger Sealed In Code Review

THE code-review.md artifact SHALL carry the review round ledger — one row per gating round with round number, P0/P1/P2/P3 counts, per-reviewer verdicts, and reviewed HEAD — as structured fields the orchestrator seals and downstream consumers read by parse, and the ledger SHALL cover every round including any disclosure round.

#### Scenario: Ledger accompanies the verdict
- **WHEN** code-review.md is sealed with its final Verdict
- **THEN** it SHALL contain a ledger row for every completed gating round, including the disclosure round when one ran

#### Scenario: Missing ledger on a multi-round review is a defect
- **IF** code-review.md records a Verdict after more than one round but carries no round ledger
- **THEN** consumers SHALL treat the review provenance as incomplete and the orchestration SHALL repair the ledger before archive

### Requirement: Disclosure Consensus Review Mode

THE code-review.md `review_mode` vocabulary SHALL include `disclosure-consensus` — a deliberately non-blind consensus round among the same resolved review-role models — alongside the blind and degraded modes, and WHERE the disclosure round consolidates at least two distinct reviewer models it SHALL satisfy a gating-required multi-model adversarial code review, WHILE `degraded-single-model` continues NOT to satisfy it.

#### Scenario: Disclosure round seals a valid gating verdict
- **WHEN** the single disclosure round produces the final joint verdict from two or more distinct models
- **THEN** code-review.md MAY record that verdict with `review_mode: disclosure-consensus` and adapter-stamped provenance, and the gate SHALL accept it wherever a multi-model adversarial review is required

#### Scenario: Disclosure mode is never self-declared for a blind round
- **IF** a round conducted blind is sealed with `review_mode: disclosure-consensus`
- **THEN** the provenance is misstated; the orchestration SHALL correct the mode to the blind vocabulary value before the verdict is consumed

---

## Acceptance criterion quality checklist

| AC ID | Testable | Solution-free | Unambiguous | Consistent | Complete |
|---|---|---|---|---|---|
| opsx-post-impl-review.verdict-under-the-severity-floor | [x] | [x] | [x] | [x] | [x] |
| opsx-post-impl-review.round-ledger-sealed-in-code-review | [x] | [x] | [x] | [x] | [x] |
| opsx-post-impl-review.disclosure-consensus-review-mode | [x] | [x] | [x] | [x] | [x] |
