<!-- authored: in-session -->
# Capability: opsx-review-convergence

## ADDED Requirements

### Requirement: Baseline Bounded Verdict Contract

A gating review verdict SHALL be fail only when at least one open finding is (a) a violation of the frozen baseline — intent.md, the change's delta acceptance criteria, design decisions, constitution, or domain invariants — or (b) an objective correctness or security defect, and findings of taste, style, alternative-design preference, or beyond-scope demands SHALL be recorded as advisory (P2/P3) and SHALL NOT cause a fail verdict.

#### Scenario: Baseline violation gates
- **WHEN** a reviewer identifies a finding that contradicts intent.md, a delta AC, a design decision, or a constitution/domain invariant
- **THEN** the finding MAY be assigned P0/P1 and MAY cause a fail verdict, citing the violated baseline element

#### Scenario: Correctness defect gates even where the baseline is silent
- **WHEN** a reviewer identifies an objective correctness or security defect not covered by any baseline statement
- **THEN** the finding MAY be assigned P0/P1 and MAY cause a fail verdict

#### Scenario: Taste cannot gate
- **IF** a finding expresses stylistic preference, an alternative design the baseline does not require, or work beyond the change's scope
- **THEN** the reviewer SHALL record it as advisory (P2/P3) and it SHALL NOT contribute to a fail verdict

### Requirement: Severity Rubric And Floor

THE gating reviewer dispatch prompt SHALL embed a P0-P3 severity rubric with a single declared severity lens (P0 confirmed baseline-violating or critical correctness/security defect; P1 must-fix gap within the contract; P2 should-fix advisory; P3 nit), and THE review verdict SHALL be pass if and only if no P0 or P1 finding remains open.

#### Scenario: Only advisory findings remain
- **WHEN** a review round concludes with zero open P0/P1 findings and one or more open P2/P3 findings
- **THEN** the verdict SHALL be pass and the P2/P3 findings SHALL be recorded and surfaced as warnings, never forcing a further fix round

#### Scenario: Open P1 blocks
- **WHILE** at least one P0 or P1 finding is open
- **THEN** the verdict SHALL be fail

#### Scenario: Rubric present in every gating dispatch
- **WHEN** a blind gating reviewer is dispatched
- **THEN** its prompt SHALL contain the severity rubric and the declared lens, so severity counts are comparable across rounds

### Requirement: Finding Routing And Follow Ups

Every review finding SHALL be routed to exactly one of: in-scope blocking (P0/P1 within the change's intended or widened scope), in-scope advisory (P2/P3), or out-of-scope — appended to a `follow-ups.md` artifact in the change directory — and THE archive step SHALL surface a non-empty follow-ups.md as explore input for a successor change.

#### Scenario: Out-of-scope finding routed without gating
- **WHEN** a finding falls outside the change's intended scope and is not required to meet the frozen intent
- **THEN** it SHALL be appended to follow-ups.md with its severity and origin round, and it SHALL NOT contribute to the gate verdict

#### Scenario: Archive surfaces the queue
- **WHEN** a change with a non-empty follow-ups.md is archived
- **THEN** the archive step SHALL report the open follow-ups and recommend them as explore input for a successor change

### Requirement: Orchestrator Round Ledger

THE orchestrator SHALL maintain a per-review-type round ledger — round number, per-severity finding counts (P0/P1/P2/P3), per-reviewer verdicts, and the HEAD reviewed — sealed into the review artifact (code-review.md for diff reviews), and the ledger, prior-round findings, and other reviewers' output SHALL NOT appear in any blind reviewer prompt.

#### Scenario: Ledger row per round
- **WHEN** a gating review round completes
- **THEN** the orchestrator SHALL append one ledger row recording the round number, severity counts, each reviewer's verdict, and the reviewed HEAD SHA

#### Scenario: Blindness preserved
- **IF** a blind reviewer dispatch prompt would include the round ledger, prior-round findings, or another reviewer's output
- **THEN** the dispatch SHALL NOT proceed as a blind round; only the explicitly marked disclosure round may disclose findings

### Requirement: Trajectory Stop And Round Budget

THE orchestration SHALL stop dispatching further blind gating review rounds when any of the following holds: (a) the latest round's P0+P1 count is zero (converged); (b) the P0+P1 count has been flat or rising for 2 consecutive rounds (treadmill); or (c) the number of completed rounds has reached the `review_max_rounds` budget (review.md front-matter, default 5 when absent), and a stop under (b) or (c) SHALL route to the split-verdict and decision-audit handling rather than sealing a pass.

#### Scenario: Convergence stops the rounds
- **WHEN** a round concludes with zero open P0/P1 findings
- **THEN** no further blind rounds SHALL be dispatched and the verdict SHALL be sealed as pass

#### Scenario: Flat trajectory trips the treadmill stop
- **WHILE** the P0+P1 count of the two most recent consecutive rounds is flat or rising
- **THEN** the orchestration SHALL stop dispatching blind rounds and proceed to disclosure/landing handling

#### Scenario: Budget exhaustion stops the rounds
- **WHEN** the completed round count reaches review_max_rounds
- **THEN** the orchestration SHALL stop dispatching blind rounds and proceed to disclosure/landing handling

#### Scenario: A stop never forges a green
- **IF** a stop fires while P0/P1 findings remain open
- **THEN** the verdict SHALL NOT be sealed as pass; the open findings SHALL flow to the decision-audit landing

### Requirement: Disclosure Round

WHEN reviewer verdicts on the same HEAD have split (at least one pass and one fail) for 2 consecutive rounds, or a trajectory/budget stop fires while a split is present, THE orchestration SHALL run exactly one non-blind disclosure round in which the same reviewers receive each other's findings and produce a joint findings set and verdict, marked `review_mode: disclosure-consensus`, and no more than one disclosure round SHALL run per change.

#### Scenario: Persistent split triggers disclosure
- **WHEN** the second consecutive split round completes
- **THEN** the orchestration SHALL dispatch the disclosure round with all reviewers' findings disclosed to each participant

#### Scenario: Disclosure round is marked
- **WHEN** the disclosure round's output is sealed
- **THEN** the artifact SHALL carry `review_mode: disclosure-consensus` distinguishing it from blind rounds

#### Scenario: Second disclosure prohibited
- **IF** open P0/P1 findings or a split persists after the disclosure round
- **THEN** the orchestration SHALL NOT dispatch another disclosure round and SHALL proceed to the decision-audit landing

### Requirement: Decision Audit Landing

IF open P0/P1 findings remain after the stop conditions and any disclosure round, THEN THE orchestration SHALL halt review cycling and present the user a tiered decision audit — need-your-call, worth-a-glance, and trust-me tiers — covering open findings, autonomous fix decisions, and all scope expansions, and it SHALL NOT seal a pass verdict, SHALL NOT continue dispatching review rounds, and SHALL NOT add reviewer models beyond the resolved review role set.

#### Scenario: Landing delivers the audit
- **WHEN** the landing fires
- **THEN** the user SHALL receive the tiered audit with each open finding, each autonomous decision, and each scope expansion assigned to a tier with one-sentence context

#### Scenario: No escalation by model shopping
- **IF** the orchestration would dispatch an additional reviewer model not in the resolved review role set to break the deadlock
- **THEN** the dispatch SHALL NOT occur; the deadlock belongs to the decision audit

#### Scenario: User ruling resumes the loop
- **WHEN** the user rules on the audit (fix, waive, or re-scope)
- **THEN** the orchestration MAY resume review rounds with the ruling applied, and the round ledger SHALL continue (not reset)

### Requirement: Scope Widening Protocol

WHILE the loop is advancing a change, WHEN a finding falls outside the intent's stated scope, THE orchestration SHALL classify it: WHERE evidence shows the finding must be addressed for the frozen intent's outcomes to hold, the scope SHALL be widened — recording an entry in the review.md `Scope Expansions` section with what widened and the evidence — and the finding fixed in-change; otherwise it SHALL be routed to follow-ups.md, and intent.md's meaning SHALL never be edited by the loop.

#### Scenario: Evidence-gated widening
- **WHEN** an out-of-scope finding is required to satisfy the frozen intent (evidence cited)
- **THEN** the orchestration SHALL log a Scope Expansions entry (what widened + evidence) and treat the finding as in-scope for gating

#### Scenario: Non-required finding deferred
- **WHEN** an out-of-scope finding is not required to satisfy the frozen intent
- **THEN** it SHALL be routed to follow-ups.md and SHALL NOT gate

#### Scenario: Widening never mutates intent
- **IF** addressing a finding would change the meaning recorded in intent.md
- **THEN** the orchestration SHALL halt and request explicit human authorization rather than widening

#### Scenario: Widenings surface to the human
- **WHEN** the change reaches the decision-audit landing or gate-green
- **THEN** every Scope Expansions entry SHALL be surfaced to the user

### Requirement: Advisory Surface Audit

WHERE a change's frozen intent states a property over the codebase (a claim of the form "no X anywhere" / "impossible via code") rather than an enumerable diff, THE orchestration SHALL dispatch one advisory blind surface-enumeration audit before implementation begins, whose findings feed the task decomposition and the intent's stated-scope prose, and advisory review output SHALL NOT trigger fix-and-re-review cycles.

#### Scenario: Property intent gets a pre-apply audit
- **WHEN** the loop begins apply for a change whose intent is property-style
- **THEN** one advisory blind audit SHALL have been dispatched to enumerate the affected surface, and its output SHALL be reflected in tasks and scope prose

#### Scenario: Advisory output cannot loop
- **IF** an advisory audit or advisory review records findings
- **THEN** the findings SHALL be recorded (tasks, scope, or follow-ups.md) without dispatching a fix-then-re-review cycle on the advisory artifact

### Requirement: Reviewer Model Stability

All blind gating review rounds of a change SHALL use the reviewer model set resolved for the `review` role at the change's first gating round, and IF the orchestration would add or substitute reviewer models mid-change, THEN the dispatch SHALL NOT proceed except when the resolved review role configuration itself has been explicitly changed by the user.

#### Scenario: Same set every round
- **WHEN** any blind gating round after the first is dispatched
- **THEN** its reviewer model set SHALL equal the set used in the first gating round

#### Scenario: Mid-change escalation prohibited
- **IF** rounds are not converging and the orchestration considers additional reviewer models for confirmation
- **THEN** no additional models SHALL be dispatched; the stop conditions and decision-audit landing govern instead

---

## Acceptance criterion quality checklist

| AC ID | Testable | Solution-free | Unambiguous | Consistent | Complete |
|---|---|---|---|---|---|
| opsx-review-convergence.baseline-bounded-verdict-contract | [x] | [x] | [x] | [x] | [x] |
| opsx-review-convergence.severity-rubric-and-floor | [x] | [x] | [x] | [x] | [x] |
| opsx-review-convergence.finding-routing-and-follow-ups | [x] | [x] | [x] | [x] | [x] |
| opsx-review-convergence.orchestrator-round-ledger | [x] | [x] | [x] | [x] | [x] |
| opsx-review-convergence.trajectory-stop-and-round-budget | [x] | [x] | [x] | [x] | [x] |
| opsx-review-convergence.disclosure-round | [x] | [x] | [x] | [x] | [x] |
| opsx-review-convergence.decision-audit-landing | [x] | [x] | [x] | [x] | [x] |
| opsx-review-convergence.scope-widening-protocol | [x] | [x] | [x] | [x] | [x] |
| opsx-review-convergence.advisory-surface-audit | [x] | [x] | [x] | [x] | [x] |
| opsx-review-convergence.reviewer-model-stability | [x] | [x] | [x] | [x] | [x] |
