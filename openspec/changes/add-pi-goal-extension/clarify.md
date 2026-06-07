# Clarify Findings

<!--
Three passes over the EARS acceptance criteria in specs/goal-loop/spec.md.
Delta-only scope (10 ACs). domain.md invariants are deployment-env facts;
none rule out the reachable combinations below.
Answer A = keep as-is. Answer B = change as proposed.
-->

## Pass 1 — Ambiguity (semantic-entropy lite)

| # | AC ref | Question | Option A (keep) | Option B (change) | Status | Resolution |
|---|---|---|---|---|---|---|
| A1 | goal-loop.judge-each-completed-turn | "the conversation transcript" given to the evaluator is ambiguous: latest worker turn's output only, or the full running conversation? | Evaluate against only the latest worker turn's surfaced output (bounded) | Evaluate against the full running conversation transcript | answered | A — evaluator sees only the latest worker turn's surfaced output (bounded cost; design D7) |
| A2 | goal-loop.bound-the-loop-with-a-turn-budget | "continuation turns" vs status's "elapsed turn count": does the initial goal-set turn count toward the budget, or only injected continuation turns? | Every evaluated turn counts, including the initial set turn | Only injected continuation turns count toward the budget | answered | A — every evaluated turn counts, including the initial set turn |

## Pass 2 — Inconsistency (pairwise antecedent overlap)

| # | AC pair | Shared antecedent | Conflict on output | Option A (keep both) | Option B (resolve) | Status | Resolution |
|---|---|---|---|---|---|---|---|
| I1 | goal-loop.complete-when-condition-met, goal-loop.bound-the-loop-with-a-turn-budget | A turn where evaluation reports met AND the elapsed turn count reaches the budget simultaneously | User-facing message + which path clears the goal ("achieved" vs "budget exhausted") | Ambiguous — both fire | Met wins: report "achieved"; budget check only applies when not met | answered | A — met wins; the budget cutoff is only evaluated when the result is not-met |

## Pass 3 — Completeness (event/state combination enumeration)

Events declared: set-command, status-command, clear-command, worker-turn-completes.
States declared: goal-active, no-goal-active.

| # | Combination | Question | Option A (intentional silence) | Option B (add new AC) | Status | Resolution |
|---|---|---|---|---|---|---|
| C1 | set-command × (worker turn already streaming) | What happens when `/goal <cond>` is issued while a worker turn is mid-stream? | Queue the directive as a follow-up, delivered when the current turn finishes | Reject with an "agent busy" message | answered | A — queue as follow-up, delivered when the current turn finishes |
| C2 | clear-command × no-goal-active | What happens on clear when no goal is active? | No-op with a "no active goal" message | answered | answered | A — no-op with "no active goal"; harmless, matches status-with-no-goal phrasing |
| C3 | worker-turn-completes × no-goal-active | What happens when a turn completes and no goal is active? | Intentional silence — the handler does nothing | Define explicit behavior | answered | answered | A — intentional silence; the agent_end handler returns early when no goal active |

## Outstanding (status != answered)

- None. All findings answered (A1, A2, I1, C1 resolved Option A; C2, C3 answered inline).

## Summary

- Pass 1 findings: 2; unanswered: 0; deferred: 0
- Pass 2 findings: 1; unanswered: 0; deferred: 0
- Pass 3 findings: 3; unanswered: 0; deferred: 0
- **Gate status:** READY for design
