# opsx-post-impl-review Specification

## Purpose
The post-implementation adversarial `code-review.md` artifact: a blind multi-model diff review whose pass verdict (with provenance and freshness fields) gates archive for changes with Code Review Mode gating-required.
## Requirements
### Requirement: Post Apply Code Review Artifact

WHILE Code Review Mode is advisory or gating-required, WHEN the implementation checks required before diff review are green (tasks complete, structural checks pass, required validation commands pass, and any retained-required verify is green), THE openspec-apply-change skill SHALL cause a `code-review.md` artifact to be produced by the review subagent (not self-authored by the orchestrator), reviewing the implemented diff against the change's intent and plan, distinct from the pre-implementation analyze review.

#### Scenario: Code review produced when pre-review checks are green
- **WHILE** Code Review Mode is advisory or gating-required
- **WHEN** tasks are complete, structural + required validation checks pass, and any retained-required verify is green
- **THEN** the review subagent SHALL author code-review.md (its body, Verdict, `Diff Base SHA`, reviewed range, `review_mode`, and adapter-stamped provenance field), and the orchestrator skill SHALL only trigger and collect it

#### Scenario: Gating-required does not deadlock under advisory verify
- **WHILE** Code Review Mode is gating-required and Verification Mode is retained-recommended or inline-only
- **WHEN** the pre-review checks (excluding the advisory verify) are green
- **THEN** code-review production SHALL still trigger, so the gate's code-review requirement cannot deadlock waiting on a verify state that the mode does not require

#### Scenario: None mode suppresses production
- **WHILE** Code Review Mode is none
- **WHEN** apply reaches a green verify state
- **THEN** the skill SHALL NOT produce code-review.md

#### Scenario: Diff base resolves for both worktree and same-tree
- **WHEN** the code review computes its diff
- **THEN** the base SHALL be the immutable `Diff Base SHA` recorded in review.md, which apply sets before the first implementation task in both worktree and same-tree modes

#### Scenario: Review baseline is intent plus the full plan
- **WHEN** the code review is performed
- **THEN** the diff SHALL be judged against intent.md together with the proposal, specs, design, plan, and tasks status, so the reviewer can check the implementation followed the approved execution and verification path

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

### Requirement: Code Review Mode Switchboard

THE review.md mode switchboard SHALL declare a `Code Review Mode` with values `none`, `advisory`, and `gating-required`, defaulting to gating-required for Scale M and above and to advisory for Scale S.

#### Scenario: Mode default by Scale
- **WHEN** review.md is authored for a Scale M change without an explicit Code Review Mode
- **THEN** the mode SHALL default to gating-required

#### Scenario: Advisory mode does not block
- **WHILE** Code Review Mode is advisory
- **WHEN** code-review.md records a fail Verdict
- **THEN** archive SHALL be permitted, opsx-gate SHALL NOT fail on the code-review check, and the failing findings SHALL be surfaced as warnings

### Requirement: Archive Gate On Code Review

WHILE Code Review Mode is gating-required, THE openspec-archive-change skill SHALL refuse to archive the change unless code-review.md exists with a Verdict of pass.

#### Scenario: Missing or failing review blocks archive
- **WHILE** Code Review Mode is gating-required
- **IF** code-review.md is absent or its Verdict is not pass
- **THEN** archive SHALL be refused and the reason SHALL be reported

#### Scenario: Passing review permits archive
- **WHILE** Code Review Mode is gating-required
- **WHEN** code-review.md exists with a pass Verdict
- **THEN** archive SHALL proceed subject to the other archive gates

---

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

