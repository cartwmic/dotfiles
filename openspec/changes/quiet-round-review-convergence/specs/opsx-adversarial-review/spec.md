# opsx-adversarial-review (delta)

## MODIFIED Requirements

### Requirement: Trajectory Stop And Round Budget

THE orchestration SHALL evaluate the following conditions IN ORDER after each completed blind gating review round, before dispatching another: (a) **quiet round** — the latest round's consolidated P0+P1 count (max across reviewers) is zero → seal `Verdict: pass` and stop dispatching rounds (converged); (b) **converging** — open P0/P1 findings remain AND the worktree HEAD has moved past the latest round's reviewed HEAD (fix commits landed in response) → fix and dispatch the next round autonomously, with NO human ruling required; (c) **thrash guard** — open P0/P1 findings remain AND the worktree HEAD equals the latest round's reviewed HEAD (no fix commits landed) → stop dispatching and route to the split-verdict and decision-audit handling; (d) **hard cap** — the number of completed rounds has reached the `review_max_rounds` budget (review.md front-matter, default 5 when absent) → stop dispatching and route to the split-verdict and decision-audit handling regardless of trajectory. All conditions SHALL be computed from per-round severity counts and the round ledger's reviewed-HEAD entries only — NO cross-round finding-identity matching of any kind. WHERE review.md front-matter sets `review_budget_mode: land-on-stop`, the pre-existing behavior governs instead: a flat-or-rising P0+P1 count across the two most recent consecutive rounds, or budget exhaustion, stops the rounds and routes to disclosure/landing. Under either mode a stop SHALL, WHILE open P0/P1 findings remain, route to the split-verdict and decision-audit handling rather than sealing a pass — WHEN the stopping round already carries zero open P0/P1, condition (a) governs and the verdict is sealed as pass.

#### Scenario: Quiet round stops the rounds
- **WHEN** a round concludes with zero open P0/P1 findings across all reviewers
- **THEN** no further blind rounds SHALL be dispatched and the verdict SHALL be sealed as pass

#### Scenario: Converging rounds continue autonomously
- **WHEN** a round concludes with open P0/P1 findings and fix commits have subsequently landed (worktree HEAD moved past that round's reviewed HEAD)
- **WHILE** the completed round count is below review_max_rounds
- **THEN** the orchestration SHALL dispatch the next blind round without landing for a human ruling

#### Scenario: Thrash guard lands for a ruling
- **IF** a round concluded with open P0/P1 findings and the worktree HEAD still equals that round's reviewed HEAD when the next dispatch is evaluated
- **THEN** the orchestration SHALL stop dispatching blind rounds and proceed to disclosure/landing handling

#### Scenario: Hard cap lands regardless of trajectory
- **WHEN** the completed round count reaches review_max_rounds
- **THEN** the orchestration SHALL stop dispatching blind rounds and proceed to disclosure/landing handling, even if fixes have been landing every round

#### Scenario: Determinism preserved
- **WHEN** any continuation/stop condition is evaluated
- **THEN** the inputs SHALL be limited to per-round consolidated severity counts, ledger reviewed-HEAD values, the current worktree HEAD, and review_max_rounds — never semantic matching of findings across rounds

#### Scenario: Opt-in legacy mode restores land-on-stop
- **WHERE** review.md front-matter sets `review_budget_mode: land-on-stop`
- **THEN** the orchestration SHALL stop on a flat-or-rising P0+P1 count across the two most recent rounds or on budget exhaustion, routing to disclosure/landing as before

#### Scenario: A stop never forges a green
- **IF** a stop fires while P0/P1 findings remain open
- **THEN** the verdict SHALL NOT be sealed as pass; the open findings SHALL flow to the decision-audit landing
