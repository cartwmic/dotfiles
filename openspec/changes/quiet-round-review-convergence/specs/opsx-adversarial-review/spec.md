# opsx-adversarial-review (delta)

## MODIFIED Requirements

### Requirement: Trajectory Stop And Round Budget

THE orchestration SHALL evaluate the following conditions IN ORDER after each completed gating review round (post-apply code-review rounds AND analyze-type gating rounds), before dispatching another, WHERE the progress signal is change-scoped: for post-apply code-review rounds, the reviewed worktree branch's HEAD having moved past the round's reviewed HEAD (verdict and ledger seals SHALL land on the integration checkout, never on the reviewed worktree branch, so only implementation fix commits move it); for analyze-type gating rounds (pre-apply, no worktree), the existence of at least one commit since the round's reviewed HEAD that touches the change's AUTHORED fix surfaces — `proposal.md`, `design.md`, `specs/**`, `tasks.md`, or `plan.md` under the change directory — WHERE orchestrator bookkeeping artifacts (the round-ledger artifact, `clarify.md`, `review.md`, `follow-ups.md`, and verdict artifacts) NEVER count as progress even when committed alongside a ledger seal, so ledger seals, finding-routing, note-logging, and sibling-change commits on the shared integration branch never register as progress: (a) **quiet round** — the latest round's consolidated P0+P1 count (max across reviewers) is zero → seal `Verdict: pass` and stop dispatching rounds (converged); (b) **converging** — open P0/P1 findings remain AND the change-scoped progress signal holds (fix commits landed in response) AND the completed round count is below `review_max_rounds` → dispatch the next round autonomously, with NO human ruling required; (c) **thrash guard** — open P0/P1 findings remain AND the change-scoped progress signal does not hold (no fix commits landed) → stop dispatching and route to the split-verdict and decision-audit handling; (d) **hard cap** — the number of completed rounds has reached the `review_max_rounds` budget (review.md front-matter, default 5 when absent) → stop dispatching and route to the split-verdict and decision-audit handling regardless of trajectory. After a round concludes with open P0/P1 findings the orchestration SHALL attempt and land the fix commits for those findings BEFORE evaluating conditions (b)/(c) — a thrash-guard stop therefore signifies that no fix commit could be landed in response to the round, never merely that findings exist immediately after it concluded. All conditions SHALL be computed from per-round severity counts and the round ledger's reviewed-HEAD entries only — NO cross-round finding-identity matching of any kind. A converging continuation under (b) selects the next round's TYPE through the unchanged Disclosure Round requirement — WHEN that requirement's disclosure trigger has fired the autonomously dispatched round SHALL be the single disclosure round, otherwise a blind round; the quiet-round evaluation governs only WHETHER the loop continues, never whether a dispatched round is blind. WHERE review.md front-matter sets `review_budget_mode: land-on-stop`, the pre-existing behavior governs instead: a flat-or-rising P0+P1 count across the two most recent consecutive rounds, or budget exhaustion, stops the rounds and routes to disclosure/landing. Under either mode a stop SHALL, WHILE open P0/P1 findings remain, route to the split-verdict and decision-audit handling rather than sealing a pass — WHEN the stopping round already carries zero open P0/P1, condition (a) governs and the verdict is sealed as pass.

#### Scenario: Quiet round stops the rounds
- **WHEN** a round concludes with zero open P0/P1 findings across all reviewers
- **THEN** no further blind rounds SHALL be dispatched and the verdict SHALL be sealed as pass

#### Scenario: Converging rounds continue autonomously
- **WHEN** a round concludes with open P0/P1 findings and fix commits have subsequently landed (the change-scoped progress signal holds)
- **WHILE** the completed round count is below review_max_rounds
- **THEN** the orchestration SHALL dispatch the next blind round without landing for a human ruling

#### Scenario: Fix lands before evaluation
- **WHEN** a round concludes with open P0/P1 findings
- **THEN** the orchestration SHALL attempt and commit the fixes for those findings BEFORE evaluating the converging/thrash conditions, so the thrash guard measures a failure to land fixes rather than the mere presence of findings

#### Scenario: Thrash guard lands for a ruling
- **IF** a round concluded with open P0/P1 findings and the change-scoped progress signal does not hold when the next dispatch is evaluated (the fix attempt landed nothing)
- **THEN** the orchestration SHALL stop dispatching blind rounds and proceed to disclosure/landing handling

#### Scenario: Analyze-type rounds measure fix-surface commits
- **WHILE** the gating rounds are analyze-type (pre-apply, no worktree exists)
- **WHEN** the continuation/stop conditions are evaluated
- **THEN** the progress signal SHALL be the existence of a commit since the round's reviewed HEAD touching the change's authored fix surfaces (proposal.md, design.md, specs/**, tasks.md, plan.md), so analyze rounds converge under quiet-round semantics without non-fix commits masquerading as progress

#### Scenario: Bookkeeping never counts as progress
- **IF** the only commits since an analyze round's reviewed HEAD touch bookkeeping artifacts (the round ledger, clarify.md, review.md, follow-ups.md, verdict artifacts) or come from other changes
- **THEN** the progress signal SHALL NOT hold and the thrash guard SHALL land the round for a human ruling — routing an out-of-scope finding to follow-ups.md or logging an Execution Note is not a fix

#### Scenario: Post-apply seals stay off the reviewed branch
- **WHEN** a post-apply round's verdict or ledger row is sealed
- **THEN** the seal commit SHALL land on the integration checkout, not the reviewed worktree branch, preserving the worktree HEAD as an honest fix-only progress signal

#### Scenario: Hard cap lands regardless of trajectory
- **WHEN** the completed round count reaches review_max_rounds
- **THEN** the orchestration SHALL stop dispatching blind rounds and proceed to disclosure/landing handling, even if fixes have been landing every round

#### Scenario: Converging continuation respects the disclosure trigger
- **WHEN** the converging condition holds and the Disclosure Round requirement's trigger (two consecutive split rounds) has fired
- **THEN** the autonomously dispatched next round SHALL be the single disclosure round rather than a blind round, leaving the disclosure-round limit unchanged

#### Scenario: Determinism preserved
- **WHEN** any continuation/stop condition is evaluated
- **THEN** the inputs SHALL be limited to per-round consolidated severity counts, ledger reviewed-HEAD values, the change-scoped progress signal (git plumbing over commit ranges and touched paths), and review_max_rounds — never semantic matching of findings across rounds

#### Scenario: Opt-in legacy mode restores land-on-stop
- **WHERE** review.md front-matter sets `review_budget_mode: land-on-stop`
- **THEN** the orchestration SHALL stop on a flat-or-rising P0+P1 count across the two most recent rounds or on budget exhaustion, routing to disclosure/landing as before

#### Scenario: A stop never forges a green
- **IF** a stop fires while P0/P1 findings remain open
- **THEN** the verdict SHALL NOT be sealed as pass; the open findings SHALL flow to the decision-audit landing

### Requirement: M-Tier Review Stack Thinning

THE adversarial-review stack SHALL be tier-conditioned by the `full_rigor` review.md front-matter flag WITHOUT weakening the 2-model blind adversarial code review at any tier: at Scale M WITHOUT `full_rigor`, clarify SHALL NOT be a standalone gating artifact (its open questions live in the proposal's `## Open Questions` section), analyze SHALL run only its deterministic checks (NO separate blind analyze dispatch), and the doneness verdict SHALL be produced within the blind code-review dispatch (the same blind reviewer, as a dedicated final required section) yet STILL sealed to a separate `doneness.md`; WITH `full_rigor` the full independent stack SHALL be required (a standalone blind clarify, a blind analyze dispatch, and an independently dispatched blind doneness judge). At every tier the code-review verdict contract, severity rubric, round ledger, review-convergence stop discipline (quiet-round default with the `review_budget_mode: land-on-stop` opt-in), disclosure round, `review_max_rounds`, and freshness/provenance binding SHALL be unchanged.

#### Scenario: Plain M folds clarify, analyze, and doneness
- **WHILE** a change is Scale M and its review.md front-matter does NOT set `full_rigor: true`
- **WHEN** the adversarial-review stack runs
- **THEN** clarify open questions SHALL live in the proposal's `## Open Questions` (no standalone clarify.md gates), analyze SHALL run only its deterministic checks with NO separate blind analyze dispatch, and the doneness verdict SHALL ride the blind code-review dispatch while STILL being sealed to a separate `doneness.md`

#### Scenario: Full-rigor requires the full independent stack
- **WHILE** a change's review.md front-matter sets `full_rigor: true`
- **WHEN** the adversarial-review stack runs
- **THEN** a standalone blind clarify, a blind analyze dispatch, and an independently dispatched blind doneness judge SHALL each be required, matching the pre-thinning top-tier behavior

#### Scenario: Code-review rigor is never reduced by thinning
- **WHEN** the stack thins at plain Scale M
- **THEN** the 2-model blind adversarial code review SHALL remain gating-required with its verdict contract, severity rubric, round ledger, review-convergence stop discipline, disclosure round, and freshness/provenance binding all unchanged

### Requirement: Disclosure Round

WHEN reviewer verdicts on the same HEAD have split (at least one pass and one fail) for 2 consecutive rounds, or a stop under the thrash guard or hard cap — or, WHERE `review_budget_mode: land-on-stop` is set, a trajectory/budget stop — fires while a split is present, THE orchestration SHALL run exactly one non-blind disclosure round in which the same reviewers receive each other's findings and produce a joint findings set and verdict, marked `review_mode: disclosure-consensus`, and no more than one disclosure round SHALL run per change.

#### Scenario: Persistent split triggers disclosure
- **WHEN** the second consecutive split round completes
- **THEN** the orchestration SHALL dispatch the disclosure round with all reviewers' findings disclosed to each participant

#### Scenario: Disclosure round is marked
- **WHEN** the disclosure round's output is sealed
- **THEN** the artifact SHALL carry `review_mode: disclosure-consensus` distinguishing it from blind rounds

#### Scenario: Second disclosure prohibited
- **IF** open P0/P1 findings or a split persists after the disclosure round
- **THEN** the orchestration SHALL NOT dispatch another disclosure round and SHALL proceed to the decision-audit landing
