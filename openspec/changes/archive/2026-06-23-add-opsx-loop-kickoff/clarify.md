# Clarify Findings

Three passes over the delta ACs in `specs/opsx-loop-kickoff/spec.md`.

## Pass 1 — Ambiguity

| # | AC ref | Question | Option A (keep) | Option B (change) | Status | Resolution |
|---|---|---|---|---|---|---|
| A1 | opsx-gate-is-the-deterministic-judge | How is the worktree `--path` resolved for the gate call? | Read `Worktree Path` from review.md; omit `--worktree` if empty (same-tree) | Require an explicit `--worktree` arg always | answered | A — read review.md Worktree Path; pass --worktree only when non-empty, matching opsx-gate's own locator |
| A2 | single-command-guaranteed-loop | Does the kickoff create the worktree? | No — it resolves an existing/declared worktree; apply owns creation (per intent non-goals) | Create the worktree if missing | answered | A — kickoff resolves only; worktree lifecycle stays in apply |

## Pass 2 — Inconsistency

| # | AC pair | Shared antecedent | Conflict | Option A | Option B | Status | Resolution |
|---|---|---|---|---|---|---|---|
| I1 | green-gate-stops × budget-exhausted-stops | a worker turn completes on the final allowed turn | both could fire (met on the budget turn) | met wins | budget wins | answered | A — evaluate the gate first; a green gate on the final turn is "achieved", not "exhausted" (mirrors goal-loop decideAfterEvaluation) |

## Pass 3 — Completeness

| # | Combination | Question | Option A | Option B | Status | Resolution |
|---|---|---|---|---|---|---|
| C1 | WHEN agent_end fires WHILE the loop is mid-evaluation | re-entrant agent_end during the async gate run | ignore re-entrant events | queue them | answered | A — guard with an `evaluating` flag (mirror goal-loop D4); ignore re-entrant agent_end |
| C2 | WHEN /opsx-loop clear issued WHILE a worker turn is in flight | should the in-flight turn be aborted? | abort the in-flight turn on clear | let it finish | answered | A — abort in-flight on clear (mirror goal-loop), so a running loop halts immediately |

## Outstanding

- None. All findings answered.

## Summary

- Pass 1: 2 findings, 0 unanswered. Pass 2: 1, 0. Pass 3: 2, 0.
- **Gate status:** READY for design
