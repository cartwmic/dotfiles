# Capability: opsx-loop-orchestration

## ADDED Requirements

### Requirement: Frozen Intent Baseline

WHEN an explore session for a change concludes, THE openspec-explore skill SHALL write the agreed intent, constraints, and invariants to an `intent.md` file in the change directory, and THE openspec-loop orchestration SHALL treat that file as an immutable baseline.

#### Scenario: Explore writes the baseline
- **WHEN** the user finishes an explore session and confirms the intent
- **THEN** `openspec/changes/<change>/intent.md` SHALL exist containing the agreed intent, initial constraints, and invariants

#### Scenario: Loop does not mutate intent
- **WHILE** the loop is advancing a change
- **IF** the orchestrator or a subagent would change the meaning recorded in intent.md
- **THEN** the orchestration SHALL halt and request explicit human authorization rather than editing intent.md autonomously

### Requirement: Single Orchestrator Loop

THE openspec-loop skill SHALL drive a change through its lifecycle within a single orchestrator agent that, each cycle, consults opsx-gate to discover the next failing check and performs the next step toward making the gate pass.

#### Scenario: Orchestrator advances on a red gate
- **WHILE** opsx-gate reports the gate is red
- **WHEN** the orchestrator begins a cycle
- **THEN** it SHALL read the gate's failed-check report and perform exactly the next step needed to address the highest-priority failed check

#### Scenario: Loop stops on a green gate
- **WHEN** opsx-gate exits 0 for the change
- **THEN** the orchestration SHALL stop advancing and SHALL report the change as ready to archive

#### Scenario: Loop is bounded
- **WHILE** the gate remains red
- **IF** the orchestration reaches the iteration budget configured as `loop_max_iterations` in review.md front-matter
- **THEN** it SHALL stop and SHALL report the budget as exhausted with the remaining failed checks

### Requirement: Subagent Review Against Baseline

THE openspec-loop orchestration SHALL delegate every review and validation-judgment step to a blind subagent, and that subagent SHALL judge the current work against the phase-appropriate baseline rather than against the orchestrator's own reasoning.

#### Scenario: Review is delegated, not self-performed
- **WHEN** a review or validation-judgment step is required
- **THEN** the orchestration SHALL dispatch a subagent that has not seen the orchestrator's prior reasoning for that step, and SHALL use the subagent's written verdict

#### Scenario: Baseline widens by phase
- **WHEN** a pre-design review subagent is dispatched
- **THEN** its baseline SHALL be intent.md
- **WHEN** a post-apply review subagent is dispatched
- **THEN** its baseline SHALL be intent.md together with the proposal, specs, design, plan, and tasks status (matching the code-review baseline), so the reviewer can check the implementation followed the approved execution and verification path

### Requirement: Harness Neutral Core With Adapters

THE openspec-loop workflow logic SHALL reside in harness-neutral artifacts (the skill body, opsx-gate, and the manifest), and subagent dispatch and loop continuation SHALL be resolved through capability hooks that degrade to inline execution when no harness adapter is available.

#### Scenario: Runs without a subagent adapter
- **IF** no subagent-dispatch capability is registered on the host
- **THEN** the orchestration SHALL perform the review step inline and mark it `review_mode: degraded-single-model`, which preserves structural enforcement but does NOT satisfy a gating-required code-review (the gate treats it as failed); the orchestration SHALL recommend running adversarial-review-cycle manually to reach a passing review

#### Scenario: Workflow substance survives adapter removal
- **WHEN** the host's loop-continuation adapter is unavailable
- **THEN** the workflow definition SHALL remain executable using the harness-neutral skill and opsx-gate, driven by a fallback continuation mechanism

#### Scenario: Single budget governs the loop
- **WHEN** the kickoff adapter starts the loop on a host whose loop runtime already has a turn budget (such as the goal extension)
- **THEN** the adapter SHALL set that runtime's turn budget from `loop_max_iterations`, so exactly one budget governs the loop and the two cannot disagree

---

## Acceptance criterion quality checklist

| AC ID | Testable | Solution-free | Unambiguous | Consistent | Complete |
|---|---|---|---|---|---|
| opsx-loop-orchestration.frozen-intent-baseline | [x] | [x] | [x] | [x] | [x] |
| opsx-loop-orchestration.single-orchestrator-loop | [x] | [x] | [x] | [x] | [x] |
| opsx-loop-orchestration.subagent-review-against-baseline | [x] | [x] | [x] | [x] | [x] |
| opsx-loop-orchestration.harness-neutral-core-with-adapters | [x] | [x] | [x] | [x] | [x] |
