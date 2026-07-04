# ADR-0027: Quiet-round convergence — progress-signal continuation supersedes count-trajectory stopping

## Status

Accepted (2026-07-04, change `quiet-round-review-convergence`; extends and
supersedes the stop-rule portion of ADR-0017)

## Context

ADR-0017's flat-or-rising severity-trajectory rule was written for the
crypt-log-redaction recirculation incident. It cannot distinguish
recirculation from fresh discovery at a constant rate: the
simplify-and-parallelize change ran 8 review rounds with findings
monotonically shrinking and every fix landing same-round, yet needed three
human budget rulings because "flat at 1×P1" read as a treadmill. The ARC
skill never had this failure — its stop condition is finding-oriented
("quiet round"), not count-oriented.

## Decision

After each gating review round, evaluate deterministically IN ORDER:
(a) quiet round — consolidated P0+P1 = 0 → seal pass, stop;
(b) converging — findings open AND change-scoped fix commits landed AND
rounds < cap → continue autonomously, no ruling (round TYPE still governed
by the disclosure trigger);
(c) thrash guard — findings open, no fix landed → decision-audit landing;
(d) hard cap — rounds ≥ `review_max_rounds` → landing regardless.
The progress signal is change-scoped per round type: post-apply = reviewed
worktree branch HEAD moved (bookkeeping artifacts never commit on the
reviewed branch); analyze-type = a commit touching the change's authored fix
surfaces (bookkeeping and sibling-change commits never count). Fixes are
landed BEFORE evaluation. `review_budget_mode: land-on-stop` opts back into
the ADR-0017 behavior; unknown values read as land-on-stop.

## Consequences

- Healthy convergence needs zero human rulings; the human decision points
  collapse to genuine thrash and the hard cap.
- A stop with open P0/P1 still never seals pass — this ADR changes when the
  loop may CONTINUE, never when it may SEAL (ADR-0019 landing intact).
- No cross-round finding-identity matching — inputs stay per-round counts,
  ledger reviewed-HEADs, and git plumbing (ADR-0007 lineage).
- Crypt-log-class thrash still lands early (no-landed-fix signal);
  fix-revert churn is bounded by the cap.
