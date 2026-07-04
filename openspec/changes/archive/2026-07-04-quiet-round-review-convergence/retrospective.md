# Retrospective: quiet-round-review-convergence

**Date:** 2026-07-04
**Scale:** M + full_rigor (first change driven end-to-end under the 3-tier schema at full rigor)

## What shipped

Q1 quiet-round budget semantics (ordered quiet→converging→thrash→cap
evaluation; `review_budget_mode` key, absent⇒quiet-round, unknown⇒land-on-stop;
change-scoped progress signals per round type). Q2 declared-token migration
sweep (`sweep.txt` + `opsx sweep` + conditional gate check + pre-round-1 skill
trigger). Q3 verdicts filled from shipped templates. Q4 riders (derived-mode
template row, usage consolidation, stray `.tmp`, fail-open audit — 9 keys,
zero divergences). ADR-0027 (supersedes ADR-0017's stop rule), ADR-0028.

## The change dogfooded its own thesis

Six gating rounds total — blind analyze 4 (blockers 4→2→1→0, quiet at R4) +
blind code review 2 (R1 3×P1 fixed same-turn, R2 both models pass, quiet) —
with **zero human rulings**, because every round's fixes landed before the
next evaluation. The predecessor took 8 rounds and 3 rulings for the same
convergence shape. The semantics were applied as authoring discipline before
they shipped as spec.

## What worked

- Blind analyze caught real spec defects pre-implementation (self-contradicting
  sibling requirement, split-brain sweep tree, always-converging analyze
  signal, bookkeeping-as-progress hole) — each round strictly narrowed.
- Round-1 code review immediately re-proved the stale-sibling-prose class
  (2×P1 on surfaces the change didn't touch) — the exact class Q2's sweep
  exists for. Fix + pins landed same turn; round 2 was quiet.
- Filling shipped templates (Q3, practiced live) still surfaced two gate
  parser gotchas — recorded below as follow-up seeds, not archaeology.

## What to improve (follow-up seeds)

- follow-ups.md commits are not in the gate's verdict-freshness trailing
  allowlist — ranges must advance through advisory-routing commits.
- Single-line HTML comments break `cr_field`'s sed comment-stripper (range
  never closes); templates should warn or the stripper should handle it.
- 5 advisories in follow-ups.md: shared root-resolution helper, `git grep -I`
  for binary SWEEP-HIT format, sweep change-dir guard, awk `-v` escape
  display, skill `--worktree` parenthetical.

## Promotion

follow-ups.md queue (5 open advisories + the 2 gate nits above) is successor
explore input; none block deployment.
