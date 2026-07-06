# opsx-adversarial-review Specification

## Purpose
TBD - created by archiving change simplify-and-parallelize-opsx-workflow. Update Purpose after archive.
## Requirements
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

THE orchestrator SHALL maintain a per-review-type round ledger — round number, per-severity finding counts (P0/P1/P2/P3), per-reviewer verdicts, and the HEAD reviewed — sealed into the review artifact for that review type (code-review.md for post-apply diff-review rounds; an appended `Round Ledger` section of analyze.md for analyze-type gating rounds; an appended `Fidelity Round Ledger` section of review.md for design-fidelity judgment rounds — review.md exists at every Scale and before worktree creation, and a design-fidelity.md full-sweep re-seal overwrites that artifact so it can never host its own history; fidelity rows SHALL be machine-parseable markdown table rows with pinned columns `| Round | Fidelity | Per-judge verdicts | Attested HEAD |` so the valve count never drifts on format), and the ledger, prior-round findings, and other reviewers' output SHALL NOT appear in any blind reviewer prompt. The `Fidelity Round Ledger` section SHALL be append-only orchestrator bookkeeping: sealing or re-sealing design-fidelity.md SHALL never remove or rewrite prior rows. A round's consolidated per-severity count SHALL be the maximum count reported by any single reviewer in that round (no cross-reviewer finding matching), so counts are deterministic and comparable across rounds without normalizing free-text findings.

#### Scenario: Ledger row per round
- **WHEN** a gating review round completes
- **THEN** the orchestrator SHALL append one ledger row recording the round number, the consolidated severity counts (max across reviewers per severity), each reviewer's verdict, and the reviewed HEAD SHA

#### Scenario: Blindness preserved
- **IF** a blind reviewer dispatch prompt would include the round ledger, prior-round findings, or another reviewer's output
- **THEN** the dispatch SHALL NOT proceed as a blind round; only the explicitly marked disclosure round may disclose findings

#### Scenario: Fidelity rounds ledger into review.md
- **WHEN** a design-fidelity judgment round seals (any overall verdict) or a human waiver ruling lands at the decision-audit landing
- **THEN** the orchestrator (or the ruling) SHALL append one row to review.md's `Fidelity Round Ledger` section recording the round number, the sealed `Fidelity` value (`waived` for a waiver ruling), each judge's verdict (or the ruling reference), and the attested integration-checkout HEAD — and a later design-fidelity.md re-seal SHALL NOT remove any row

### Requirement: Trajectory Stop And Round Budget

THE orchestration SHALL evaluate the following conditions IN ORDER after each completed gating review round (post-apply code-review rounds AND analyze-type gating rounds), before dispatching another, WHERE the progress signal is change-scoped: for post-apply code-review rounds, the reviewed worktree branch's HEAD having moved past the round's reviewed HEAD (NO change-directory bookkeeping artifact — verdict artifacts, the round ledger, follow-ups.md, review.md, clarify.md — SHALL be committed on the reviewed worktree branch; they land on the integration checkout per the writeback-owner and path-scoped-commit disciplines, so only implementation fix commits move the reviewed branch); for analyze-type gating rounds (pre-apply, no worktree), the existence of at least one commit since the round's reviewed HEAD that touches the change's AUTHORED fix surfaces — `proposal.md`, `design.md`, `specs/**`, `tasks.md`, or `plan.md` under the change directory — WHERE orchestrator bookkeeping artifacts (the round-ledger artifact, `clarify.md`, `review.md`, `follow-ups.md`, and verdict artifacts) NEVER count as progress even when committed alongside a ledger seal, so ledger seals, finding-routing, note-logging, and sibling-change commits on the shared integration branch never register as progress: (a) **quiet round** — the latest round's consolidated P0+P1 count (max across reviewers) is zero → seal `Verdict: pass` and stop dispatching rounds (converged); (b) **converging** — open P0/P1 findings remain AND the change-scoped progress signal holds (fix commits landed in response) AND the completed round count is below `review_max_rounds` → dispatch the next round autonomously, with NO human ruling required; (c) **thrash guard** — open P0/P1 findings remain AND the change-scoped progress signal does not hold (no fix commits landed) → stop dispatching and route to the split-verdict and decision-audit handling; (d) **hard cap** — the number of completed rounds has reached the `review_max_rounds` budget (review.md front-matter, default 5 when absent) → stop dispatching and route to the split-verdict and decision-audit handling regardless of trajectory. After a round concludes with open P0/P1 findings the orchestration SHALL attempt and land the fix commits for those findings BEFORE evaluating conditions (b)/(c) — a thrash-guard stop therefore signifies that no fix commit could be landed in response to the round, never merely that findings exist immediately after it concluded. All conditions SHALL be computed from per-round severity counts and the round ledger's reviewed-HEAD entries only — NO cross-round finding-identity matching of any kind. A converging continuation under (b) selects the next round's TYPE through the unchanged Disclosure Round requirement — WHEN that requirement's disclosure trigger has fired the autonomously dispatched round SHALL be the single disclosure round, otherwise a blind round; the quiet-round evaluation governs only WHETHER the loop continues, never whether a dispatched round is blind. WHERE review.md front-matter sets `review_budget_mode: land-on-stop`, the pre-existing behavior governs instead: a flat-or-rising P0+P1 count across the two most recent consecutive rounds, or budget exhaustion, stops the rounds and routes to disclosure/landing. Under either mode a stop SHALL, WHILE open P0/P1 findings remain, route to the split-verdict and decision-audit handling rather than sealing a pass — WHEN the stopping round already carries zero open P0/P1, condition (a) governs and the verdict is sealed as pass.

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

#### Scenario: Post-apply bookkeeping stays off the reviewed branch
- **WHEN** a post-apply round's verdict or ledger row is sealed, or any change-directory bookkeeping artifact (follow-ups.md, review.md, clarify.md) is written during a post-apply round
- **THEN** the commit SHALL land on the integration checkout, not the reviewed worktree branch, preserving the worktree HEAD as an honest fix-only progress signal for the thrash guard

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

#### Scenario: A resume ruling extends the exhausted budget
- **WHEN** the user's ruling directs further fixing and re-review after a hard-cap/budget stop (or, WHERE `review_budget_mode: land-on-stop` is set, a trajectory stop)
- **THEN** the ruling SHALL grant a recorded round-budget extension (a ledger entry noting the new effective budget), so resumed rounds are dispatchable rather than immediately re-landing on the same exhausted stop condition

#### Scenario: A user waiver clears the blocking set without a forced green
- **WHEN** the user waives an open P0/P1 finding at the audit
- **THEN** the finding SHALL be recorded as user-waived (routed to follow-ups.md with the waiver noted) and removed from the open P0/P1 set, so the severity floor's `pass` condition is satisfied by explicit human authorization rather than by the loop forcing a green verdict over a still-open blocker

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
- **THEN** its reviewer model set SHALL equal the set used in the first gating round, UNLESS the user has explicitly reconfigured the resolved `review` role since that round (in which case the change of set is logged in the ledger and applies only to subsequent rounds)

#### Scenario: Mid-change escalation prohibited
- **IF** rounds are not converging and the orchestration considers additional reviewer models for confirmation
- **THEN** no additional models SHALL be dispatched; the stop conditions and decision-audit landing govern instead

---

### Requirement: Prose Surface Fidelity

THE discipline's prose surfaces — the orchestrator skill, the apply-mode reference, and the code-review template — SHALL state the ledger-repair recovery obligation (a sealed multi-round Verdict without a round ledger is a provenance defect to repair before archive) and SHALL NOT label review findings in a way that implies cross-reviewer finding matching, so operators reading any surface see the same discipline the specs define.

#### Scenario: Recovery obligation stated on the surfaces
- **WHEN** an operator reads the orchestrator skill or the apply-mode reference
- **THEN** the ledger-repair red flag SHALL be present: a sealed multi-round Verdict with no ledger row is a provenance defect — repair the ledger before archive

#### Scenario: Findings section does not imply convergence matching
- **WHEN** a code-review artifact is authored from the shipped template
- **THEN** its findings section heading SHALL be neutral (`Findings`), not `Convergent findings`, since consolidated counts use the max-across-reviewers rule with no cross-reviewer finding matching

#### Scenario: Surface drift is caught deterministically
- **IF** a future edit removes the recovery red flag or reintroduces a convergence-implying findings heading
- **THEN** the required surface test SHALL fail

---

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

#### Scenario: Diff base resolves from the worktree
- **WHEN** the code review computes its diff
- **THEN** the base SHALL be the immutable `Diff Base SHA` recorded in review.md, which apply sets at `opsx/<change>` worktree creation before the first implementation task — worktree execution is the only model, so no other diff-base source exists

#### Scenario: Review baseline is intent plus the full plan
- **WHEN** the code review is performed
- **THEN** the diff SHALL be judged against intent.md together with the proposal, specs, design, plan, and tasks status, so the reviewer can check the implementation followed the approved execution and verification path

### Requirement: Adversarial Review With Degradation

THE code-review production SHALL use the adversarial-review capability over the diff when that capability is available, and IF no adversarial-review capability is registered, THEN it SHALL fall back to a single-model review and SHALL mark code-review.md as degraded.

#### Scenario: Adversarial path used when available
- **WHERE** the adversarial-review capability resolves to a registered skill
- **WHEN** code review runs
- **THEN** the review SHALL be conducted blind over the diff — with this capability's single disclosure round as the sole sanctioned non-blind exception, marked `review_mode: disclosure-consensus` — and the converged findings SHALL be recorded in code-review.md

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

THE code-review.md `Verdict` SHALL be `pass` if and only if no P0 or P1 finding remains open under this capability's baseline-bounded verdict contract, and open P2/P3 findings SHALL be recorded in the artifact as warnings without blocking the verdict, the gate, or archive.

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

### Requirement: Sealed Doneness Verdict Artifact

THE doneness judge SHALL record its verdict in a `doneness.md` artifact in the change
directory carrying a machine-readable `Doneness` field whose value is exactly `satisfied`
or `not`, and WHILE the value is `not` THE artifact SHALL enumerate the specific unmet
gaps as a list, so downstream consumers (the gate and the stall detector) read the verdict
and the gap set by field parse rather than model judgment.

#### Scenario: Satisfied verdict is a sealed field
- **WHEN** the doneness judge concludes the frozen intent's outcomes are met by the diff
- **THEN** `doneness.md` SHALL contain the line `**Doneness:** satisfied` and SHALL carry
  its provenance and reviewed-range fields

#### Scenario: Not-satisfied verdict enumerates gaps
- **WHEN** the doneness judge concludes one or more intent outcomes are unmet
- **THEN** `doneness.md` SHALL contain `**Doneness:** not` and SHALL list each unmet gap as
  a distinct bullet under a `Gaps` heading, each gap being a short stable phrase a consumer
  can normalize and compare across turns

#### Scenario: Absent or unparseable verdict is treated as not-satisfied
- **IF** `doneness.md` is absent, or its `Doneness` field is missing or holds a value other
  than `satisfied` or `not`
- **THEN** consumers SHALL treat doneness as not established (equivalent to `not`), never as
  a permissive pass

### Requirement: Blind Scope-Anchored Judge

THE doneness judge SHALL be a blind judgment on the resolved `review` role model, judging
the frozen `intent.md` against the actual `Diff Base SHA..HEAD` diff and the change's delta
acceptance criteria, and SHALL rule `satisfied` only when the intent's stated outcomes are
met and NOTHING beyond them is demanded. THE DISPATCH CHANNEL SHALL be tier-conditioned:
WITH the `full_rigor` review.md front-matter flag it SHALL be an INDEPENDENT blind subagent
dispatched separately from the code-review reviewers; at Scale M WITHOUT `full_rigor` it
SHALL instead be answered by ONE designated blind code-review reviewer as a dedicated final
required section of that dispatch. WHERE the code-review dispatch resolves more than one
`review`-role model, the designated doneness reviewer SHALL be exactly ONE of them chosen
deterministically (the FIRST model in the resolved `review` role set), so a single sealed
`doneness.md` verdict and a single-model provenance stamp (`blind-single-judge`) result
regardless of how many reviewers the code review uses, and the other reviewers SHALL NOT
each emit a competing doneness verdict. In BOTH channels the judgment stays blind (fresh
context, no orchestrator reasoning), on the `review` role model, scope-anchored to the
frozen intent, and sealed to a separate `doneness.md`; the 2-model blind code review itself
is NOT reduced by co-locating the doneness section in one reviewer's dispatch.

#### Scenario: Judge runs blind on the review role
- **WHEN** the doneness verdict is produced (either channel)
- **THEN** the judgment SHALL be made with fresh context (no orchestrator reasoning)
  on the model resolved for the `review` role, and SHALL read the frozen intent, the diff,
  and the delta ACs as its baseline

#### Scenario: Dispatch channel follows the full_rigor flag
- **WHILE** the doneness verdict is required
- **WHEN** the orchestration produces it
- **THEN** WITH `full_rigor` set it SHALL dispatch an INDEPENDENT blind doneness judge (a subagent separate from the code-review reviewers); at plain Scale M it SHALL ride the blind code-review dispatch as a dedicated final section by one designated blind reviewer, and in either case the verdict SHALL be sealed to a separate `doneness.md`

#### Scenario: One designated reviewer answers doneness on a multi-model code-review dispatch
- **WHILE** the change is plain Scale M (no `full_rigor`) and the code-review dispatch resolves two or more distinct `review`-role models
- **WHEN** the doneness section rides that dispatch
- **THEN** exactly ONE reviewer (the FIRST model in the resolved `review` role set) SHALL author the doneness section, its provenance SHALL be stamped `blind-single-judge` with that model's identity, and a single `doneness.md` verdict SHALL be sealed — the remaining reviewers SHALL NOT each emit a separate competing doneness verdict, and the 2-model blind code review SHALL remain unweakened

#### Scenario: Scope anchor forbids gold-plating
- **WHILE** the judge is ruling on satisfaction
- **IF** the diff meets every stated outcome of the frozen intent
- **THEN** the judge SHALL rule `satisfied` even if further beyond-scope improvements are
  imaginable, and SHALL NOT record gaps that demand work outside the frozen intent

#### Scenario: No new model role is introduced
- **WHEN** the doneness judge resolves its model
- **THEN** it SHALL use the existing `review` role via `opsx models review`, and no
  `doneness` model role SHALL be added to the model-config surface

### Requirement: Freshness Bound Verdict

THE doneness verdict SHALL be valid only WHILE (a) its recorded reviewed range equals
`Diff Base SHA..<current-HEAD>` recomputed from the located worktree, (b) its recorded Diff
Base SHA equals the immutable Diff Base SHA recorded in review.md, AND (c) its recorded
frozen-intent content hash equals `sha256(intent.md)` recomputed from the change directory,
so a `satisfied` verdict recorded against an earlier HEAD, a different diff base, or a
mutated intent cannot pass.

#### Scenario: Stale doneness verdict is invalid
- **WHILE** `doneness.md` records a reviewed range
- **IF** that recorded `Diff Base SHA..HEAD` does not equal the range recomputed from the
  current located worktree HEAD
- **THEN** the verdict SHALL be treated as stale and not established, forcing a re-judge

#### Scenario: Verdict judged against a mutated intent or wrong diff base is invalid
- **WHILE** `doneness.md` records a frozen-intent hash and a Diff Base SHA
- **IF** the recorded frozen-intent hash does not equal `sha256(intent.md)`, OR the recorded
  Diff Base SHA does not equal the immutable Diff Base SHA in review.md
- **THEN** the verdict SHALL be treated as judged against the wrong baseline and not
  established, forcing a re-judge

#### Scenario: New commit invalidates a prior satisfied verdict
- **WHILE** a prior `satisfied` verdict exists
- **WHEN** the implementation HEAD advances with a new commit
- **THEN** the recorded reviewed range no longer matches the recomputed range and the
  verdict SHALL no longer count as satisfied until re-judged against the new HEAD

### Requirement: Anti-Self-Forge Provenance

THE subagent-dispatch adapter SHALL stamp `doneness.md` with a reviewer-provenance field —
recording the judging `review`-role model identity, the review mode, the frozen-intent
content hash, and the Diff Base SHA it judged — rather than the orchestrator or the judge
subagent writing that stamp in-band itself. The review-mode vocabulary for doneness is
`blind-single-judge` (the normal case: one independent blind subagent judge) or
`adversarial-multimodel` (the optional stronger form, ≥2 distinct models); consumers SHALL
treat a verdict whose provenance is absent, or whose review mode is
`degraded-single-model` or any value outside that vocabulary, as not established,
matching the adapter-stamped code-review provenance posture: it is a tripwire against
accidental self-marking in normal flow, NOT a cryptographic guarantee — a same-UID actor
that both bypasses dispatch AND forges the stamp is out of the threat model, exactly as the
live in-session authoring-marker check concedes (a post-hoc gate cannot force a model
against a same-UID actor).

#### Scenario: Provenance is adapter-stamped, not agent-written
- **WHEN** a doneness verdict is sealed
- **THEN** the reviewer-provenance field SHALL be written by the subagent-dispatch adapter
  (not authored in-band by the orchestrator or the judge subagent), recording the
  review-role model identity, the review mode, the frozen-intent content hash, and the Diff
  Base SHA

#### Scenario: Missing or degraded provenance is not established
- **IF** `doneness.md` carries a `satisfied` verdict but lacks the adapter-stamped
  reviewer-provenance field, or that field records a review mode other than
  `blind-single-judge` or `adversarial-multimodel` (including `degraded-single-model`
  and unknown values)
- **THEN** consumers SHALL treat the verdict as not established (equivalent to `not`)

### Requirement: Scale-Gated With Waiver

THE doneness verdict SHALL be a required check WHILE the change declares Scale M or above
and `doneness_mode` is `required`, and WHERE `doneness_mode` is `waived` (with a recorded
non-empty `doneness_waiver_rationale`) or the change is below Scale M, the doneness verdict
SHALL NOT be a required check, mirroring the existing validation-source waiver.

#### Scenario: Required at Scale M and above by default
- **WHILE** the change declares Scale M or above and `doneness_mode` is absent or `required`
- **WHEN** doneness is evaluated
- **THEN** a satisfied, fresh, provenanced doneness verdict SHALL be required

#### Scenario: Waiver with rationale lets Scale M and above pass without a verdict
- **WHERE** `doneness_mode` is `waived` with a recorded non-empty `doneness_waiver_rationale`
  in review.md front-matter
- **WHEN** doneness is evaluated
- **THEN** the doneness verdict SHALL NOT be required and its absence SHALL NOT fail the
  check

#### Scenario: Waiver without a rationale does not take effect
- **WHERE** `doneness_mode` is `waived` but no non-empty `doneness_waiver_rationale` is
  recorded
- **WHILE** the change declares Scale M or above
- **THEN** the waiver SHALL NOT take effect and a satisfied, fresh, provenanced doneness
  verdict SHALL remain required

#### Scenario: Below Scale M skips doneness
- **WHILE** the change declares Scale below M
- **WHEN** doneness is evaluated
- **THEN** the doneness verdict SHALL NOT be a required check

---

### Requirement: Reviewer Tree Identity Attestation

THE blind reviewer/judge dispatch prompt SHALL require the subagent, BEFORE reviewing, to attest the tree it is actually executing in — record the verbatim output of `git rev-parse HEAD` (a full 40-hex SHA; any other form is a missing attestation) and of `git rev-parse --show-toplevel`, as machine-readable own-line fields at the top of its findings output (`Attested HEAD: <40-hex sha>` and `Attested Path: <toplevel path>`) — and THE orchestrator SHALL count a reviewer verdict toward gating ONLY WHEN the attested HEAD literal equals the full SHA of the dispatched range head AND the attested path, canonicalized (realpath), equals the canonicalized root of the dispatched tree. FOR post-implementation dispatches (code review, doneness) the dispatched tree is the change's `opsx/<change>` worktree — worktree execution is the only implementation model, so the path check always discriminates the reviewed worktree from the integration checkout and every other tree. FOR proposal-phase judgment classes (clarify, analyze, design fidelity), the dispatched tree IS the integration checkout ALWAYS — the carve-out is keyed to the judgment CLASS (purpose), never to whether an implementation worktree happens to exist: these judgments never receive their own worktree (the `opsx/<change>` worktree is the implementation tree, not a judgment tree), their judged inputs live in the integration checkout's change directory, and a fidelity re-judge dispatched AFTER the implementation worktree exists (digest staled by a post-worktree design edit) still attests the integration-checkout root and HEAD and still counts — the attested path SHALL equal the canonicalized integration-checkout root and the attested HEAD SHALL equal the integration-checkout HEAD at dispatch, with the HEAD check carrying discrimination. Post-implementation dispatch classes (code review, doneness) NEVER use this carve-out. A verdict with a missing or mismatched attestation SHALL be treated as INVALID — distinct from fail: it SHALL NOT satisfy multi-model gating, SHALL NOT enter the round ledger as a reviewer verdict, and SHALL NOT count toward the `review_max_rounds` trajectory — and the orchestrator SHALL record the incident and re-dispatch the reviewer (or repair the reviewer set) rather than sealing. WHEN two consecutive dispatch attempts of the same round yield NO countable verdict (all reviewers INVALID), THE orchestrator SHALL stop re-dispatching and route to the decision-audit landing with a dispatch-integrity error rather than retrying unbounded. WHEN sealing `code-review.md` (and `doneness.md` or `design-fidelity.md` when an independently dispatched judge produced them), THE orchestrator SHALL record the single `**Attested HEAD:**` value only when every counted reviewer's attestation matches it.

#### Scenario: Attestation preamble required in every dispatch
- **WHEN** a blind reviewer or judge subagent is dispatched
- **THEN** the dispatch prompt SHALL instruct it to record `Attested HEAD: <git rev-parse HEAD output>` and `Attested Path: <resolved working directory>` as its first findings-output lines before any review content

#### Scenario: Wrong-tree verdict is invalid, not fail
- **IF** a returned verdict's attested HEAD does not rev-parse equal to the dispatched range head, or its attested path does not resolve to the dispatched worktree root
- **THEN** the orchestrator SHALL treat the verdict as INVALID — excluded from multi-model gating, absent from the round ledger's reviewer verdicts, and not counted toward `review_max_rounds` — record the incident, and re-dispatch

#### Scenario: Integration-checkout path fails the attestation
- **IF** a reviewer dispatched against a change worktree (any post-implementation dispatch) attests the integration checkout's toplevel path
- **THEN** the verdict SHALL be INVALID — the path check discriminates unconditionally for post-implementation dispatches now that no same-tree mode exists

#### Scenario: Pre-worktree judgment attests the integration checkout
- **WHILE** a clarify, analyze, or design-fidelity judgment is dispatched before any `opsx/<change>` worktree exists
- **WHEN** the judge attests the integration checkout's HEAD and canonicalized root
- **THEN** the attestation SHALL be countable — the integration checkout is the dispatched tree for proposal-phase judgments, and the HEAD equality check carries the discrimination

#### Scenario: Post-worktree fidelity re-judge still attests the integration checkout
- **WHILE** an `opsx/<change>` implementation worktree exists and a design.md edit has staled the sealed fidelity digest
- **WHEN** the orchestrator re-dispatches the fidelity judge and it attests the integration checkout's HEAD and root
- **THEN** the attestation SHALL be countable — the carve-out is purpose-keyed to the judgment class, so the re-seal the gate anticipates is producible and the change never strands INVALID

#### Scenario: Pre-worktree judgment attesting the wrong tree is invalid
- **WHILE** a pre-worktree judgment is dispatched against the integration checkout at a recorded HEAD
- **IF** the returned attestation's HEAD does not equal the integration-checkout HEAD at dispatch, or its canonicalized path does not equal the integration-checkout root
- **THEN** the verdict SHALL be INVALID with the standard exclusions — the carve-out changes which tree is attested, never whether the equality checks discriminate

#### Scenario: Missing attestation is invalid
- **IF** a returned findings output carries no attestation fields, or an `Attested HEAD` that is not a full 40-hex SHA literal
- **THEN** the verdict SHALL be treated as INVALID with the same exclusions

#### Scenario: All-invalid rounds terminate at the landing
- **IF** two consecutive dispatch attempts of the same review round produce zero countable verdicts (every reviewer INVALID)
- **THEN** the orchestrator SHALL stop re-dispatching and route to the decision-audit landing with a dispatch-integrity error

#### Scenario: Sealed artifact carries the matched attestation
- **WHEN** the orchestrator seals code-review.md (or doneness.md / design-fidelity.md produced by an independently dispatched judge)
- **THEN** it SHALL record `**Attested HEAD:**` equal to the value every counted reviewer attested, and SHALL NOT seal while counted reviewers' attestations disagree

### Requirement: Read Only Reviewer Dispatch

THE orchestrator SHALL capture a deterministic snapshot immediately before dispatching a review round's reviewer/judge subagents and an identically captured snapshot immediately after the last of them returns — covering the REVIEWED WORKTREE and, WHEN the integration checkout is a different tree (the worktree-always norm), ALSO the integration checkout: each tree's `git rev-parse HEAD` plus its `git status --porcelain=v1` output with ONLY the change's orchestrator-bookkeeping files excluded from the comparison — `openspec/changes/<change>/review.md` and `openspec/changes/<change>/follow-ups.md`, the only in-window writes permitted — while the change's judged inputs and remaining artifacts (intent.md, design.md, `specs/**`, proposal.md, clarify.md, tasks.md, plan.md, and all verdict artifacts) are NEVER excluded, so a dispatched judge mutating the very files it judges voids the round — and THE orchestrator SHALL NOT write to either covered tree outside that exclusion while the round window is open. FOR the integration checkout, a HEAD advance across the window SHALL NOT by itself void the round WHEN every intervening commit (`git diff --name-only <pre-HEAD>..<post-HEAD>` plus commit enumeration) exclusively touches `openspec/changes/<other-change>/` paths of OTHER changes OR the dispatched change's own bookkeeping files (review.md, follow-ups.md — the permitted in-window writes, symmetric whether committed or uncommitted) — concurrent orchestrators legitimately land path-scoped artifact/bookkeeping commits on the shared integration branch, and voiding on them would reintroduce at the review layer the tree contention worktree-mandatory exists to eliminate; any intervening commit touching paths outside those exemptions (code, specs, templates, the dispatched change's judged inputs) SHALL void the round. Working-tree (porcelain) deltas SHALL void the round when they lie outside BOTH the dispatched change's own excluded paths AND other changes' `openspec/changes/<other-change>/` paths — a concurrent change's uncommitted authoring inside its own change directory is the same legitimate-concurrency class as its path-scoped commits (the pre-worktree phase shares one working tree across all changes in propose/clarify/analyze/fidelity) and SHALL NOT void; porcelain deltas anywhere else (code, specs, templates, and the dispatched change's own judged inputs — which the narrow bookkeeping exclusion never covers) SHALL always void. IF the round is voided — snapshots differ in the reviewed worktree, a disqualifying integration-checkout delta occurred — mutation cannot be attributed among concurrently dispatched reviewers, so THE orchestrator SHALL treat ALL of that round's verdicts as INVALID (with the same exclusions as a mismatched attestation), restore the mutated tree to its pre-dispatch state surgically — `git restore` only tracked paths whose porcelain status changed across the window; delete only untracked paths present in the post-window snapshot and absent from the pre-window snapshot; the restore and delete sets SHALL exclude other changes' `openspec/changes/<other-change>/` paths (symmetric with the void carve-outs — a sibling's concurrent authoring is never restored or deleted) and the dispatched change's own excluded paths; NEVER a blanket `git clean` and NEVER ignored or pre-existing untracked state — and record the incident in the round ledger / Execution Notes before proceeding. The snapshot and restore SHALL use plain git commands only (deterministic, model-free).

#### Scenario: Reviewer mutation voids the round
- **IF** the post-window snapshot differs from the pre-window snapshot for a review round in the reviewed worktree (after excluding only the change's bookkeeping files, review.md and follow-ups.md)
- **THEN** all of that round's verdicts SHALL be INVALID, the tree SHALL be restored to the pre-dispatch state, and the incident SHALL be recorded

#### Scenario: Judge tampering with judged inputs voids the round
- **WHILE** a design-fidelity (or clarify/analyze) round window is open on the integration checkout
- **IF** the post-window snapshot shows a delta in the dispatched change's own intent.md, design.md, or `specs/**` (the judged inputs)
- **THEN** the round SHALL be voided with all verdicts INVALID — the judged inputs are never part of the bookkeeping exclusion, so a judge cannot silently rewrite the material it is judging before the orchestrator seals digests over it

#### Scenario: Integration-checkout mutation also voids the round
- **WHILE** the reviewed worktree and the integration checkout are different trees
- **IF** the integration checkout's post-window snapshot shows a working-tree (porcelain) delta outside the dispatched change's own paths, or an intervening commit touching paths outside other changes' `openspec/changes/<other-change>/` directories
- **THEN** all of that round's verdicts SHALL be INVALID, the integration checkout SHALL be restored surgically (working-tree deltas only — committed history is never rewritten), and the incident SHALL be recorded

#### Scenario: Concurrent bookkeeping commit does not void the round
- **WHILE** a review round's window is open on change A
- **IF** a concurrent change B's orchestrator lands a commit on the integration branch touching only `openspec/changes/B/` paths
- **THEN** change A's round SHALL NOT be voided by that HEAD advance — the deterministic path check attributes it to legitimate concurrent bookkeeping, preserving parallel loops

#### Scenario: Concurrent uncommitted authoring does not void the round
- **WHILE** change A's pre-worktree review window is open on the integration checkout
- **IF** the post-window porcelain snapshot differs from the pre-window snapshot only in paths under a concurrent change B's `openspec/changes/B/` directory (B mid-authoring, not yet committed)
- **THEN** change A's round SHALL NOT be voided — sibling change-dir authoring is legitimate concurrency, and only porcelain deltas outside every change directory (or inside A's inputs) void A's round

#### Scenario: Restore is surgical
- **WHEN** the orchestrator restores after a snapshot delta
- **THEN** it SHALL `git restore` only tracked paths whose status changed across the window and delete only untracked paths introduced during the window, never pre-existing untracked or ignored state

#### Scenario: Restore never touches sibling change directories
- **WHILE** change A's voided round triggers a surgical restore of the shared integration checkout
- **IF** a concurrent change B introduced untracked or modified paths under `openspec/changes/B/` during A's window
- **THEN** A's restore SHALL NOT delete or revert any `openspec/changes/B/` path — the restore set is scoped symmetrically with the void carve-outs, so sibling authoring survives A's incident handling

#### Scenario: Clean dispatch counts normally
- **WHILE** the pre- and post-window snapshots are identical in every covered tree
- **WHEN** a verdict's attestation also matches
- **THEN** the verdict SHALL be counted normally toward gating and the ledger

### Requirement: Design Fidelity Judge

WHERE a change carries a `design.md`, THE workflow SHALL obtain a blind design-fidelity judgment BEFORE tasks generation: for EVERY delta acceptance criterion of the change, the judge SHALL answer whether the design mechanism cited (or discoverable) for that AC semantically entails the AC's guarantee AS WRITTEN, recording one verdict row per AC — `entailed | not-entailed | not-covered` — with evidence; an AC whose only design coverage is a nominal citation to a section that does not address the guarantee SHALL be `not-covered`. THE judge SHALL apply a bounded contract mirroring the baseline-bounded reviewer contract: a `not-entailed`/`not-covered` row blocks ONLY on clear non-entailment of the AC as written; WHERE the AC's guarantee is ambiguous, the judge SHALL route an advisory clarify-class finding instead of blocking, recorded in the sealed artifact's `Advisory Findings` section (advisory rows never occupy the three-value verdict column). Judge model resolution SHALL follow the existing role-model machinery via the `review` role — no dedicated fidelity role is introduced. Intent-mandate violations (a design decision rejecting or weakening something the frozen intent mandates) and rationale↔mechanism contradictions within a design decision ARE in scope and fall out of the per-AC sweep as evidence. Dispatch channel: WHILE `full_rigor: true`, the fidelity judgment SHALL ride the existing blind analyze dispatch as a REQUIRED section of EVERY dispatched judge's prompt, with the verdict STILL sealed to the separate `design-fidelity.md`; at plain Scale M or a design-bearing Scale S/XS, one narrow post-design blind mini-dispatch SHALL produce the same sealed artifact. WHEN the dispatch resolves multiple judge models, THE orchestrator SHALL consolidate deterministically and fail-closed: per AC, the consolidated row verdict is the worst across counted judges for that AC reference (AC references are enumerable keys — key-indexed worst-of, `not-entailed`/`not-covered` outrank `entailed`; no free-text finding matching), and the sealed overall `Fidelity` SHALL be `violated` iff any counted judge's overall is `violated` or any consolidated row is blocking (any-block-wins, mirroring the severity-floor posture); the sealed per-AC table records the consolidated rows. Re-judgments SHALL be full sweeps (never delta-scoped, no cross-round finding matching). The fidelity dispatch SHALL follow the reviewer tree-identity attestation and read-only dispatch window protocols under the purpose-keyed integration-checkout carve-out: fidelity judgments (first seal or re-judge, before or after an implementation worktree exists) are proposal-phase judgments whose dispatched tree IS the integration checkout, and the judge attests its HEAD and root (Reviewer Tree Identity Attestation). THE dispatch prompt SHALL hand every judge the same canonical AC enumeration — requirement name + scenario title enumerated from the change's delta spec files — as the consolidation key set; an AC present in the canonical enumeration but absent from a counted judge's table SHALL consolidate as `not-covered` (fail-closed), so key drift can never surface a permissive row. Each sealed fidelity verdict SHALL be recorded as a round-ledger entry in the `Fidelity Round Ledger` section of review.md (the fidelity-type host defined by Orchestrator Round Ledger — append-only, present at every Scale, available pre-worktree, orchestrator-sealed), and THE escalation valve SHALL count consecutive `violated` entries from that ledger — persisting across sessions and across design-fidelity.md re-seals — not from any state inside the re-sealed artifact. WHEN two consecutive sealed `violated` verdicts land — regardless of which rows failed; no per-row cross-round comparison is performed, consistent with the full-sweep rule — THE orchestrator SHALL route to the decision-audit landing for a human ruling rather than looping unbounded; a human waiver SHALL be recorded in the artifact by the ruling, never self-authored, AND the ruling SHALL append a `waived` row to the Fidelity Round Ledger: the valve counts only consecutive `violated` rows not separated by a `waived` or `delivered` row, so a resolved streak never re-fires the valve against a superseded round — a fresh post-waiver `violated` starts a new count of one.

#### Scenario: Oxide D3 shape judged not-entailed
- **WHILE** a delta AC guarantees a structural property ("safe by construction") and the design's cited mechanism is manual per-site handling
- **WHEN** the fidelity judge sweeps that AC
- **THEN** the row SHALL be `not-entailed` with evidence naming the mechanism/guarantee gap, and the overall verdict SHALL be `violated`

#### Scenario: Nominal citation is not coverage
- **WHILE** an AC cites a design section that does not substantively address the AC's guarantee
- **WHEN** the judge sweeps that AC
- **THEN** the row SHALL be `not-covered`, not `entailed`

#### Scenario: Ambiguous guarantee routes to clarify, not a block
- **WHILE** an AC's guarantee admits materially divergent readings
- **WHEN** the judge cannot rule non-entailment for the AC as written
- **THEN** it SHALL record an advisory clarify-class finding for that AC rather than a blocking `not-entailed` row

#### Scenario: full_rigor rides the analyze dispatch
- **WHILE** the change declares `full_rigor: true`
- **WHEN** the blind analyze dispatch runs
- **THEN** the dispatch SHALL include the fidelity sweep as a required section and the fidelity verdict SHALL be sealed to `design-fidelity.md` (separate from analyze.md)

#### Scenario: Plain-M design-bearing change gets the mini-dispatch
- **WHILE** the change is plain Scale M (no full_rigor) and carries design.md
- **WHEN** design authoring completes
- **THEN** a narrow blind fidelity mini-dispatch SHALL produce the sealed `design-fidelity.md` before tasks generation

#### Scenario: Split judges consolidate fail-closed
- **WHILE** a full_rigor fidelity sweep dispatches two judges
- **IF** one judge's overall is `delivered` and the other's is `violated` (or the judges disagree on an AC row)
- **THEN** the orchestrator SHALL seal `Fidelity: violated` (any-block-wins) and the consolidated per-AC table SHALL carry the worst verdict per AC reference — never a permissive pick

#### Scenario: Escalation valve after two consecutive violated verdicts
- **IF** the round ledger records two consecutive sealed `violated` fidelity verdicts, regardless of which rows failed in each
- **THEN** the orchestrator SHALL route to the decision-audit landing with the fidelity history rather than dispatching a third judgment automatically, and SHALL NOT attempt per-row matching across the two sealed verdicts

#### Scenario: Valve count persists across sessions
- **WHILE** one sealed `violated` fidelity verdict is recorded in review.md's `Fidelity Round Ledger` section
- **WHEN** a fresh orchestrator session seals a second consecutive `violated`
- **THEN** the valve SHALL fire from the ledger's record — the count never resets merely because design-fidelity.md was re-sealed (a full-sweep re-seal overwrites the artifact, never the ledger) or the session restarted

### Requirement: Findings File Sole Verdict Source

FOR every reviewer/judge dispatch (code review, doneness, design fidelity, and judged clarify/analyze passes), THE orchestrator SHALL derive the verdict, the findings, and the attestation EXCLUSIVELY from the subagent's findings output file; the subagent's conversational reply SHALL never be a verdict input. A findings file that is absent, or lacks the required verdict line/fields, SHALL consolidate as INVALID (per the invalid-not-fail semantics: excluded from gating, the round ledger, and the round budget; incident recorded; re-dispatch or reviewer-set repair) regardless of any claim in the conversational reply.

#### Scenario: Reply claims pass but file is absent
- **IF** a dispatched reviewer's reply asserts a verdict while its findings output file is absent
- **THEN** the orchestrator SHALL consolidate that reviewer as INVALID, record the incident, and re-dispatch — never counting the reply's claim

#### Scenario: Reply contradicts the findings file
- **WHILE** a findings file records findings and a verdict
- **IF** the reviewer's conversational reply summarizes them differently
- **THEN** the orchestrator SHALL use the file's content exclusively and ignore the reply's characterization

#### Scenario: Verdict-less findings file is invalid
- **IF** a findings file exists but lacks the required verdict line or attestation fields
- **THEN** the orchestrator SHALL treat that reviewer as INVALID with the standard exclusions rather than inferring a verdict from partial content

