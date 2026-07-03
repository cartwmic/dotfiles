# Clarify Findings

<!--
Three passes over the EARS acceptance criteria in specs/**/spec.md, judged
against the FROZEN intent.md baseline. Autonomous loop: every finding is
resolved here with the more conservative / intent-faithful option; no finding
is left unanswered and nothing is asked of the user. Where a resolution needed
a wording change, the delta spec was edited minimally (validate --strict kept
green).
-->

## Pass 1 — Ambiguity (semantic-entropy lite)

| # | AC ref | Question | Option A (keep) | Option B (change) | Status | Resolution |
|---|---|---|---|---|---|---|
| A1 | opsx-review-convergence.trajectory-stop-and-round-budget:R(b) | "flat or rising for 2 consecutive rounds" — is the treadmill measured over one round-to-round transition (2 rounds of data) or over two transitions (3 rounds)? Paraphrases diverged. | Two transitions (needs 3 rounds) | One transition — compare the two most recent rounds (the reading the scenario "Flat trajectory trips the treadmill stop" already encodes) | answered | **B (edit applied).** The scenario already binds it to "the two most recent consecutive rounds," and intent phrases it "flat or rising for 2 consecutive rounds" = 2 rounds of data = one transition. Requirement reworded to "the P0+P1 count of the two most recent consecutive rounds is flat or rising," matching the scenario and intent. Earliest fire = after round 2. Declining trajectories (intent's protected "4 rounds to 0/0") never trip. |
| A2 | opsx-review-convergence.severity-rubric-and-floor:R | P0 ("confirmed baseline-violating or critical") and P1 ("must-fix gap within the contract") overlap: a baseline violation could be tagged either. Does the fuzzy boundary threaten the "comparable across rounds" guarantee intent calls a hard dependency? | Keep rubric as-is | Add a discriminator between P0 and P1 baseline violations | answered | **A (keep).** Both gating (`pass ⟺ no open P0/P1`) and the trajectory count operate on the **P0+P1 sum**, so the P0↔P1 boundary is neutral to every downstream decision in this change; comparability depends on the P0/P1-vs-P2/P3 line, which the rubric + single declared lens fix. Adding a finer discriminator would be beyond-scope precision. No edit. |

## Pass 2 — Inconsistency (pairwise antecedent overlap)

| # | AC pair | Shared antecedent | Conflict on output | Option A (keep both) | Option B (resolve) | Status | Resolution |
|---|---|---|---|---|---|---|---|
| I1 | trajectory-stop-and-round-budget:R(a) vs R(c)/(b) + decision-audit-landing:R | A stopping round where the budget is exhausted **and** the round's open P0+P1 = 0 | (a) "seal pass" vs the clause "(b)/(c) SHALL … rather than sealing a pass" | Leave both (budget stop always routes to landing) | Narrow: (b)/(c) route to landing only WHILE open P0/P1 remain; a zero-blocker stopping round is convergence (a) → seal pass | answered | **B (edit applied).** Decision-audit-landing already guards on "IF open P0/P1 remain," so a zero-blocker budget stop has nothing to audit; the unconditional "rather than sealing a pass" contradicted that and (a). Reworded to "(b)/(c) SHALL, WHILE open P0/P1 findings remain, route … — WHEN the stopping round already carries zero open P0/P1, condition (a) governs and the verdict is sealed as pass." Conservative: still never forges green while a blocker is open. |
| I2 | reviewer-model-stability:R vs its "Same set every round" scenario | A blind round after the first is dispatched | Requirement permits an exception ("resolved review role … explicitly changed by the user"); scenario asserts absolute set-equality | Keep scenario absolute | Narrow scenario to carry the same user-reconfig exception | answered | **B (edit applied).** Intent's prohibition targets orchestrator-side reviewer shopping / ad-hoc mid-change additions, **not** user sovereignty over the `review` role config. Scenario THEN clause gained "UNLESS the user has explicitly reconfigured the resolved `review` role since that round (logged in the ledger, applies only to subsequent rounds)." Keeps trajectory comparability honest (set change is recorded, not silent) and keeps requirement/scenario consistent. |

## Pass 3 — Completeness (event/state combination enumeration)

| # | Combination | Question | Option A (intentional silence) | Option B (add new AC) | Status | Resolution |
|---|---|---|---|---|---|---|
| C1 | User selects **waive** at the decision audit × an open P1 remains × archive gate requires `Verdict: pass` × severity floor `pass ⟺ no open P0/P1` | How does a user waive unblock the change without the loop "forcing green," given the floor makes pass impossible while a P1 is open and archive demands pass? | Accept as undefined | Define what a waive does to the open-blocking set | answered | **B (edit applied).** Undefined here is a real deadlock (waive → loop resumes → re-hits same P1 forever). Added scenario "A user waiver clears the blocking set without a forced green": a waived P0/P1 is recorded as user-waived (routed to follow-ups.md with the waiver noted) and removed from the open P0/P1 set, so the floor's `pass` is satisfied by **explicit human authorization**, not by the loop overriding an open blocker. Consistent with intent's "the user rules … never forced green." |
| C2 | A gating **analyze**-type review runs multiple rounds × where is its round ledger sealed? | Intent commits to the ledger being "mirrored for analyze rounds," but only opsx-post-impl-review concretely seals it in code-review.md; the analyze sealing surface was unnamed. | Silent — analyze mirroring unaddressed | Name the analyze sealing surface in the review-type-neutral requirement | answered | **B (edit applied).** The generic Orchestrator Round Ledger requirement is review-type-neutral and already governs analyze rounds; the parenthetical "(code-review.md for diff reviews)" read as exclusive. Broadened to "(e.g., code-review.md for post-apply diff-review rounds; the pre-implementation analyze artifact for analyze-type gating rounds)." Concrete analyze **field-format** mechanization stays deferred (proposal scopes only 3 modified capabilities; intent's "mechanize only if prose fails" posture) — behavioral commitment now matches intent without over-specifying. |
| C3 | A resolved `review` set with only **one** model (single-model or no-adapter degraded path) × split/disclosure protocol | With one reviewer, verdicts can never "split" and a disclosure round can't "consolidate at least two distinct models" — is the single-model case left dangling? | Accept as undefined (governed elsewhere) | Draft an AC for the single-reviewer path | answered | **A (intentional silence).** Correct behavior already emerges from existing ACs: split protocol simply never fires (no split possible), the ledger records one per-reviewer verdict, and degraded-single-model does **not** satisfy Constitution IX for skill edits (live opsx-post-impl-review + opsx-loop-orchestration), so a single-model round cannot green-gate this change regardless. No new AC needed; adding one would duplicate the degraded-mode contract. |
| C4 | A participating model becomes **unavailable during the non-blind disclosure round** (disclosure degrades to <2 models) | Does a degraded disclosure round still seal a gating verdict? | Accept as undefined | Draft a degraded-disclosure AC | answered | **A (intentional silence).** Covered transitively: disclosure-consensus satisfies the multi-model requirement only "WHERE it consolidates at least two distinct reviewer models" (opsx-post-impl-review) — a sub-two disclosure fails that WHERE clause, and "Second disclosure prohibited" routes any residual open P0/P1 / split to the decision-audit landing. Max-one-disclosure + landing already bound the outcome; no separate AC required. |

## Outstanding (status != answered)

- None. All 8 findings resolved (0 unanswered, 0 deferred).

## Summary

- Pass 1 findings: 2; unanswered: 0; deferred: 0
- Pass 2 findings: 2; unanswered: 0; deferred: 0
- Pass 3 findings: 4; unanswered: 0; deferred: 0
- **Spec edits applied:** `specs/opsx-review-convergence/spec.md` — Trajectory Stop wording (A1, I1), Reviewer Model Stability "Same set every round" scenario (I2), Orchestrator Round Ledger parenthetical (C2), new Decision Audit Landing waiver scenario (C1).
- **Gate status:** READY for design
