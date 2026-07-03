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

### Requirement: Review Dispatch Bound By Convergence Discipline

THE openspec-loop orchestration SHALL conduct gating review rounds under the opsx-review-convergence discipline: full-diff blind re-review each round, an orchestrator-maintained round ledger, the trajectory/budget stop conditions, at most one disclosure round on persistent split, and the decision-audit landing when open P0/P1 findings survive the stops.

#### Scenario: Re-dispatch consults the stop conditions first
- **WHEN** a gating review round returns a fail verdict and fixes have been committed
- **THEN** the orchestration SHALL evaluate the convergence stop conditions (converged, treadmill trajectory, round budget) before dispatching the next blind round, and SHALL NOT dispatch when a stop condition holds

#### Scenario: Non-convergence lands, never spins
- **IF** stop conditions fire with open P0/P1 findings (after any disclosure round)
- **THEN** the orchestration SHALL present the decision-audit landing to the user instead of continuing review cycles or escalating to additional reviewer models

#### Scenario: Landing halts loop continuation
- **WHEN** the decision-audit landing is presented
- **THEN** the orchestration SHALL stop the drive-to-green loop's continuation by setting `loop_hold: true` with a reason pointing at the audit (per the terminal-landing requirement); WHERE the loop host does not support `loop_hold`, performing no further change-directory or commit activity (so the host's stall detection stops the loop) remains the fallback — in both cases presenting the audit exactly once rather than re-presenting it on every re-injected turn

### Requirement: Pre Apply Surface Audit Dispatch

WHERE the frozen intent is property-style (a codebase-wide property claim rather than an enumerable diff), THE orchestration SHALL dispatch the advisory surface audit before the first implementation task, and SHALL feed its enumeration into tasks.md and the intent's stated-scope prose before gating reviews begin.

#### Scenario: Audit precedes implementation
- **WHEN** apply begins for a property-style intent without a completed surface audit
- **THEN** the orchestration SHALL dispatch the advisory audit before executing implementation tasks

#### Scenario: Enumerable-diff intents skip the audit
- **WHERE** the intent enumerates its scope concretely
- **THEN** no surface audit dispatch is required

### Requirement: Scope Widening Handled In The Loop

WHILE the loop is advancing a change, WHEN a gating reviewer or the doneness judge reports a finding outside the intent's stated scope, THE orchestration SHALL apply the opsx-review-convergence scope-widening protocol (as specified by that capability) rather than silently fixing, silently dropping, or halting on every out-of-scope finding.

#### Scenario: Widening logged before fixing
- **WHEN** the orchestration decides an out-of-scope finding is required to meet the frozen intent
- **THEN** it SHALL record the Scope Expansions entry (what + evidence) in review.md before committing the fix

#### Scenario: Deferral is visible
- **WHEN** the orchestration routes an out-of-scope finding to follow-ups.md
- **THEN** the routing SHALL be recorded with the finding's severity and origin so the archive step can surface it

---

### Requirement: Terminal landings set the loop hold

THE orchestrator SHALL, WHEN declaring a landing state that must not be re-driven by
loop continuation — a decision-audit landing after review non-convergence, a terminal
green-gate report already presented, or any stop that awaits a human ruling — set
`loop_hold: true` with a non-empty `loop_hold_reason` in the change's review.md
front-matter — the same copy the loop host resolves from the integration checkout, so
the hold is observable to the host — committed as part of the landing turn, instead of
relying on prose
announcements or stall-guard exhaustion, so the host loop observes the landing
deterministically. The orchestrator SHALL NEVER clear a `loop_hold` itself — clearing is
reserved to the human named re-arm.

#### Scenario: Decision-audit landing holds the loop
- **WHEN** the orchestrator presents a decision audit after review stop conditions fire
- **THEN** it SHALL set `loop_hold: true` with a reason pointing at the audit before ending the turn, and the loop SHALL NOT re-inject a continuation

#### Scenario: Orchestrator never clears its own hold
- **WHILE** review.md carries `loop_hold: true`
- **WHEN** the orchestrator concludes further work is warranted
- **THEN** it SHALL surface that recommendation to the user and SHALL NOT remove the hold fields itself

#### Scenario: Hold is written to the copy the loop host reads
- **WHILE** the change's verdict artifacts (verify.md, code-review.md, doneness.md) live in the apply worktree
- **WHEN** the orchestrator sets a landing hold
- **THEN** it SHALL write and commit the `loop_hold` fields in the review.md resolved from the INTEGRATION checkout (the copy the loop host and gate read), not solely the worktree copy, so the hold cannot be split-brained into invisibility

