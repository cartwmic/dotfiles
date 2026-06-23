# Clarify Findings

Three passes over the delta ACs in `specs/**/spec.md` (delta scope only).

## Pass 1 — Ambiguity (semantic-entropy lite)

| # | AC ref | Question | Option A (keep) | Option B (change) | Status | Resolution |
|---|---|---|---|---|---|---|
| A1 | opsx-gate-enforcement.gate-exit-code-contract | Does a green gate mean "ready to archive" (archive not yet done) or does it require the change already be archived? | Green = ready to archive; archive is the action the green gate authorizes | Green requires the change already moved to `changes/archive/` | answered | A — green = ready to archive; the loop stops at green and archive runs as the authorized follow-up action |
| A2 | opsx-loop-orchestration.single-orchestrator-loop | What does "highest-priority failed check" order by? | The gate's report order (first red wins) | A separate semantic priority the orchestrator computes | answered | A — order by the gate's report order; missing-artifact failures emit in lifecycle **dependency** order (review, intent, proposal, specs, clarify, design, analyze, tasks, plan, verify, code-review), superseding the earlier cost-order rationale (round-2 P1-2) |
| A3 | opsx-loop-orchestration.subagent-review-against-baseline | "blind subagent" — blind to what exactly? | Blind to the orchestrator's prior reasoning for that step; sees only artifacts + baseline | Fully fresh process with zero shared context | answered | A — matches adversarial-review-cycle's blind definition; reviewer sees artifacts + baseline, not the orchestrator's reasoning |

## Pass 2 — Inconsistency (pairwise antecedent overlap)

| # | AC pair | Shared antecedent | Conflict on output | Option A (keep both) | Option B (resolve) | Status | Resolution |
|---|---|---|---|---|---|---|---|
| I1 | opsx-gate-enforcement.deterministic-verdict-reading × opsx-post-impl-review.archive-gate-on-code-review | Code Review Mode = gating-required AND code-review.md absent | Gate is silent on absent code-review (only fails if present+not-pass), but archive refuses on absent | Keep both; gate green possible while archive refuses | Make opsx-gate treat absent code-review.md as a failed check whenever Code Review Mode = gating-required | answered | B — opsx-gate reads Code Review Mode from review.md and fails on absent code-review.md when gating-required; gate and archive stay consistent (new scenario added to deterministic-verdict-reading) |

## Pass 3 — Completeness (event/state combination enumeration)

| # | Combination | Question | Option A (intentional silence) | Option B (add new AC) | Status | Resolution |
|---|---|---|---|---|---|---|
| C1 | WHEN apply runs WHILE Worktree Mode = same-tree (explicit override) | Does apply still capture a base SHA for file-contract diffs? | Undefined — existing same-tree behavior unchanged | Add AC: same-tree records Diff Base SHA = pre-apply HEAD | answered | B — same-tree records `Diff Base SHA` = pre-apply HEAD before the first task (superseded by round-3 REV3-008 / round-4 F2); gate freshness locator resolves same-tree HEAD as current repo HEAD |
| C2 | WHILE loop active WHEN iteration budget exhausted AND a worktree exists | Is the worktree removed or preserved for inspection? | Preserve worktree + branch for human inspection | Auto-remove worktree on budget exhaustion | answered | A — preserve worktree + opsx/<change> branch; removal happens only on successful archive (already implied by worktree-lifecycle-ownership: remove only after gate green) |
| C3 | WHEN apply reaches verify green WHILE Code Review Mode = none | Is code-review.md produced at all? | Produce always (mode only governs gating) | Skip production when mode = none | answered | B — mode=none suppresses production; producing an ungating review wastes a subagent. The "Post Apply Code Review Artifact" requirement is implicitly conditioned on mode != none; design.md will state this explicitly |

## Outstanding (status != answered)

- None. All findings answered.

## Summary

- Pass 1 findings: 3; unanswered: 0; deferred: 0
- Pass 2 findings: 1; unanswered: 0; deferred: 0
- Pass 3 findings: 3; unanswered: 0; deferred: 0
- **Gate status:** READY for design
