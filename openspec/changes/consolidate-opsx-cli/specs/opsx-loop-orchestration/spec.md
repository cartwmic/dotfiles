<!-- authored: in-session -->
# Capability: opsx-loop-orchestration

Delta for consolidate-opsx-cli: migrate command-name references from the retired
standalone executables to the unified `opsx <subcommand>` form. Behavior is unchanged;
only the invocation surface is renamed (the executables are removed by this change, so
the spec-of-record must name commands that exist). Full requirement content restated
per the MODIFIED-delta rule.

## MODIFIED Requirements

### Requirement: Single Orchestrator Loop

THE openspec-loop skill SHALL drive a change through its lifecycle within a single orchestrator agent that, each cycle, consults opsx gate to discover the next failing check and performs the next step toward making the gate pass.

#### Scenario: Orchestrator advances on a red gate
- **WHILE** opsx gate reports the gate is red
- **WHEN** the orchestrator begins a cycle
- **THEN** it SHALL read the gate's failed-check report and perform exactly the next step needed to address the highest-priority failed check

#### Scenario: Loop stops on a green gate
- **WHEN** opsx gate exits 0 for the change
- **THEN** the orchestration SHALL stop advancing and SHALL report the change as ready to archive

#### Scenario: Loop is bounded
- **WHILE** the gate remains red
- **IF** the orchestration reaches the iteration budget configured as `loop_max_iterations` in review.md front-matter
- **THEN** it SHALL stop and SHALL report the budget as exhausted with the remaining failed checks

### Requirement: Harness Neutral Core With Adapters

THE openspec-loop workflow logic SHALL reside in harness-neutral artifacts (the skill body, opsx gate, and the manifest), and subagent dispatch and loop continuation SHALL be resolved through capability hooks that degrade to inline execution when no harness adapter is available.

#### Scenario: Runs without a subagent adapter
- **IF** no subagent-dispatch capability is registered on the host
- **THEN** the orchestration SHALL perform the review step inline and mark it `review_mode: degraded-single-model`, which preserves structural enforcement but does NOT satisfy a gating-required code-review (the gate treats it as failed); the orchestration SHALL recommend running adversarial-review-cycle manually to reach a passing review

#### Scenario: Workflow substance survives adapter removal
- **WHEN** the host's loop-continuation adapter is unavailable
- **THEN** the workflow definition SHALL remain executable using the harness-neutral skill and opsx gate, driven by a fallback continuation mechanism

#### Scenario: Single budget governs the loop
- **WHEN** the kickoff adapter starts the loop on a host whose loop runtime already has a turn budget (such as the goal extension)
- **THEN** the adapter SHALL set that runtime's turn budget from `loop_max_iterations`, so exactly one budget governs the loop and the two cannot disagree

---

