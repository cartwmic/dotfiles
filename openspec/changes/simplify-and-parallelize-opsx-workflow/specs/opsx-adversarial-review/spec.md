<!-- authored: delegate spec-consolidation -->
# Capability: opsx-adversarial-review

This capability consolidates the three retired capabilities **opsx-review-convergence**,
**opsx-post-impl-review**, and **opsx-doneness-judge** into a single adversarial-review
capability: the baseline-bounded verdict contract, severity rubric, finding routing, round
ledger, trajectory/budget stop, disclosure round, decision-audit landing, and scope-widening
discipline; the post-implementation `code-review.md` artifact and its mode switchboard and
archive gate; and the sealed `doneness.md` verdict. Every requirement and scenario from all
three retired capabilities is carried over verbatim, with NO behavior change beyond the B1
tier-thinning edits: at Scale M WITHOUT the `full_rigor` flag the clarify questions live in
the proposal's `## Open Questions` (no standalone clarify artifact), analyze runs only its
deterministic checks (no separate blind analyze dispatch), and the doneness verdict rides
the blind code-review dispatch (same blind reviewer, still sealed to a separate
`doneness.md`); WITH `full_rigor` the full independent stack (standalone blind clarify,
blind analyze dispatch, independently dispatched blind doneness judge) is required. The
2-model blind adversarial code review is NEVER weakened: the verdict contract, severity
rubric, round ledger, trajectory stop, disclosure round, `review_max_rounds`, and the
freshness/provenance binding all carry over UNCHANGED.

## ADDED Requirements

### Requirement: M-Tier Review Stack Thinning

THE adversarial-review stack SHALL be tier-conditioned by the `full_rigor` review.md front-matter flag WITHOUT weakening the 2-model blind adversarial code review at any tier: at Scale M WITHOUT `full_rigor`, clarify SHALL NOT be a standalone gating artifact (its open questions live in the proposal's `## Open Questions` section), analyze SHALL run only its deterministic checks (NO separate blind analyze dispatch), and the doneness verdict SHALL be produced within the blind code-review dispatch (the same blind reviewer, as a dedicated final required section) yet STILL sealed to a separate `doneness.md`; WITH `full_rigor` the full independent stack SHALL be required (a standalone blind clarify, a blind analyze dispatch, and an independently dispatched blind doneness judge). At every tier the code-review verdict contract, severity rubric, round ledger, trajectory/budget stop, disclosure round, `review_max_rounds`, and freshness/provenance binding SHALL be unchanged.

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
- **THEN** the 2-model blind adversarial code review SHALL remain gating-required with its verdict contract, severity rubric, round ledger, trajectory/budget stop, disclosure round, and freshness/provenance binding all unchanged

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

THE orchestrator SHALL maintain a per-review-type round ledger — round number, per-severity finding counts (P0/P1/P2/P3), per-reviewer verdicts, and the HEAD reviewed — sealed into the review artifact for that review type (code-review.md for post-apply diff-review rounds; an appended `Round Ledger` section of analyze.md for analyze-type gating rounds), and the ledger, prior-round findings, and other reviewers' output SHALL NOT appear in any blind reviewer prompt. A round's consolidated per-severity count SHALL be the maximum count reported by any single reviewer in that round (no cross-reviewer finding matching), so counts are deterministic and comparable across rounds without normalizing free-text findings.

#### Scenario: Ledger row per round
- **WHEN** a gating review round completes
- **THEN** the orchestrator SHALL append one ledger row recording the round number, the consolidated severity counts (max across reviewers per severity), each reviewer's verdict, and the reviewed HEAD SHA

#### Scenario: Blindness preserved
- **IF** a blind reviewer dispatch prompt would include the round ledger, prior-round findings, or another reviewer's output
- **THEN** the dispatch SHALL NOT proceed as a blind round; only the explicitly marked disclosure round may disclose findings

### Requirement: Trajectory Stop And Round Budget

THE orchestration SHALL stop dispatching further blind gating review rounds when any of the following holds: (a) the latest round's P0+P1 count is zero (converged); (b) the P0+P1 count of the two most recent consecutive rounds is flat or rising (treadmill); or (c) the number of completed rounds has reached the `review_max_rounds` budget (review.md front-matter, default 5 when absent), and a stop under (b) or (c) SHALL, WHILE open P0/P1 findings remain, route to the split-verdict and decision-audit handling rather than sealing a pass — WHEN the stopping round already carries zero open P0/P1, condition (a) governs and the verdict is sealed as pass.

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

#### Scenario: A resume ruling extends the exhausted budget
- **WHEN** the user's ruling directs further fixing and re-review after a trajectory or budget stop
- **THEN** the ruling SHALL grant a recorded round-budget extension (a ledger entry noting the new effective budget), so resumed rounds are dispatchable rather than immediately re-landing on the same exhausted stop condition

#### Scenario: A user waiver clears the blocking set without a forced green
- **WHEN** the user waives an open P0/P1 finding at the audit
- **THEN** the finding SHALL be recorded as user-waived (routed to follow-ups.md with the waiver noted) and removed from the open P0/P1 set, so the severity floor's `pass` condition is satisfied by explicit human authorization rather than by the loop forcing a green verdict over a still-open blocker

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

