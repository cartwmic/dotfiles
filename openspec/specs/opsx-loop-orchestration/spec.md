# opsx-loop-orchestration Specification

## Purpose
The single-orchestrator drive-to-completion loop behind the deterministic gate: frozen intent baseline, earliest-blocking-failure repair each turn, blind delegated review verdicts, and a hard stop at gate-green — the loop never archives.
## Requirements
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

#### Scenario: Doneness judge baseline is intent and diff
- **WHEN** the doneness judge subagent is dispatched
- **THEN** its baseline SHALL be the frozen intent.md together with the actual
  `Diff Base SHA..HEAD` diff and the change's delta acceptance criteria, and it SHALL rule
  `satisfied` only when the intent's stated outcomes are met without demanding beyond-scope
  work

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

### Requirement: Doneness Judge Dispatch

THE openspec-loop orchestration SHALL dispatch an independent blind doneness judge on the resolved `review` role model and seal its verdict into `doneness.md` with provenance and a fresh reviewed range, WHILE a change requires a doneness verdict (Scale M or above and `doneness_mode` is `required`), doing so after the mechanical gate checks pass and before treating the gate as green, so intent-satisfaction is judged upstream and the gate only reads the sealed field.

#### Scenario: Judge dispatched after mechanical checks pass
- **WHILE** the doneness verdict is required for the change
- **WHEN** the mechanical gate checks (structure, required artifacts, tasks, validation,
  verify, code-review) pass but no fresh satisfied doneness verdict exists
- **THEN** the orchestration SHALL dispatch the blind doneness judge on the `review` role
  model and write its verdict to `doneness.md` before re-running opsx gate

#### Scenario: Orchestrator never self-authors the doneness verdict
- **WHEN** a doneness verdict is produced
- **THEN** it SHALL be authored by the blind judge subagent (not the orchestrator), and its
  reviewer-provenance field SHALL be stamped by the subagent-dispatch adapter (not written
  in-band by the orchestrator), matching the adapter-stamped code-review delegation rule

#### Scenario: No dispatch adapter degrades to a failed check, never a silent pass
- **WHILE** the doneness verdict is required but no subagent-dispatch adapter is registered
- **WHEN** the orchestration attempts to produce the verdict
- **THEN** it SHALL either leave `doneness.md` absent or seal it with `Doneness: not` (it
  SHALL NOT seal a `satisfied` verdict stamped `degraded-single-model`), and record a notice
  that a green doneness verdict is reachable only via a dispatch-capable harness or an
  explicit `doneness_mode: waived` with a non-empty rationale; the gate SHALL treat the
  absent or `not` verdict as a failed check. Constraining the adapterless state to
  absent-or-`not` (never a degraded `satisfied`) maps it to the stall detector's bounded
  gap-set/empty-set signal, so an adapterless Scale >= M loop STALLS rather than spinning
  forever on a re-reproducible degraded `satisfied`. The harness-neutral guarantee is that
  ENFORCEMENT persists without the adapter (the deterministic gate still evaluates the
  check), NOT that a passing verdict is reachable adapterless

#### Scenario: Bare waiver at Scale M and above is resolved within the loop
- **WHILE** the change declares Scale M or above and `doneness_mode` is `waived` without a
  non-empty `doneness_waiver_rationale` (so the gate still fails `doneness`)
- **WHEN** the orchestration evaluates the turn
- **THEN** it SHALL either dispatch the doneness judge or surface the missing-rationale
  requirement to the worker, so the failing gate is resolvable within the loop rather than
  only by the stall backstop bailing out

#### Scenario: Judge re-dispatched on a stale verdict
- **WHILE** a prior doneness verdict exists but its reviewed range no longer matches the
  current HEAD
- **WHEN** the orchestration evaluates doneness
- **THEN** it SHALL re-dispatch the doneness judge against the current HEAD rather than reuse
  the stale verdict

