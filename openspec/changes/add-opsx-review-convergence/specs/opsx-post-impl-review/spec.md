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

### Requirement: Waiver Sealed Pass

WHEN the user waives the remaining open P0/P1 findings at the decision-audit landing, THE orchestration SHALL re-seal the code-review.md `Verdict` as `pass` carrying a `waived_by_user` field that lists the waived findings and the waiver rationale, with the reviewed range unchanged (no new HEAD is required), so the gate and archive read a sealed pass reached by explicit human authorization rather than remaining blocked on a fail verdict no reviewer can refresh.

#### Scenario: Waiver reaches a consumable pass
- **WHEN** every open P0/P1 finding has been user-waived at the landing
- **THEN** code-review.md SHALL record `Verdict: pass` with the `waived_by_user` field populated and the existing reviewed range retained, and the gate SHALL accept it wherever a pass verdict is required

#### Scenario: Waiver never self-authored
- **IF** a `waived_by_user` field would be written without a user ruling at the decision-audit landing
- **THEN** the re-seal SHALL NOT occur; only an explicit user ruling authorizes a waiver-sealed pass

## MODIFIED Requirements

### Requirement: Adversarial Review With Degradation

THE code-review production SHALL use the adversarial-review capability over the diff when that capability is available, and IF no adversarial-review capability is registered, THEN it SHALL fall back to a single-model review and SHALL mark code-review.md as degraded.

#### Scenario: Adversarial path used when available
- **WHERE** the adversarial-review capability resolves to a registered skill
- **WHEN** code review runs
- **THEN** the review SHALL be conducted blind over the diff — with the single opsx-review-convergence disclosure round as the sole sanctioned non-blind exception, marked `review_mode: disclosure-consensus` — and the converged findings SHALL be recorded in code-review.md

#### Scenario: Degraded single-model fallback
- **IF** no adversarial-review capability is registered
- **THEN** code-review.md SHALL still be produced, SHALL set `review_mode: degraded-single-model`, and SHALL carry a degraded-mode notice in its header

#### Scenario: Degraded review does not satisfy Constitution IX
- **WHILE** the change modifies an existing skill (Constitution IX) or runs without a subagent-dispatch adapter
- **IF** code-review.md `review_mode` is degraded-single-model
- **THEN** opsx-gate and archive SHALL treat the code-review check as failed, since a self-authored or single-model review does not satisfy the multi-model adversarial requirement

---

## Acceptance criterion quality checklist

| AC ID | Testable | Solution-free | Unambiguous | Consistent | Complete |
|---|---|---|---|---|---|
| opsx-post-impl-review.verdict-under-the-severity-floor | [x] | [x] | [x] | [x] | [x] |
| opsx-post-impl-review.round-ledger-sealed-in-code-review | [x] | [x] | [x] | [x] | [x] |
| opsx-post-impl-review.disclosure-consensus-review-mode | [x] | [x] | [x] | [x] | [x] |
| opsx-post-impl-review.waiver-sealed-pass | [x] | [x] | [x] | [x] | [x] |
| opsx-post-impl-review.adversarial-review-with-degradation | [x] | [x] | [x] | [x] | [x] |
