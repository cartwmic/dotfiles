# Follow-ups

<!--
Out-of-scope finding queue (opsx-review-convergence). Skill-managed, NOT in the
schema artifact graph — authored from this template at the lifecycle moment the
FIRST out-of-scope finding is routed (matching the verify/retrospective/doneness
pattern); its absence never fails schema completeness or the gate.

Routing rule: a review finding outside the intent's stated scope lands here
UNLESS evidence shows it is REQUIRED to meet the frozen intent (that case widens
scope via review.md "Scope Expansions" instead). Findings recorded here are
advisory for THIS change: they never gate, never force a fix round.

User-waived P0/P1 findings from the decision-audit landing are ALSO recorded
here with `user-waived` status — the waiver rationale mirrors the
`waived_by_user` field sealed in code-review.md.

At archive: a non-empty follow-ups.md is reported and recommended as explore
input for a successor change.
-->

**Change:** <change-name>
**Created:** YYYY-MM-DD (first out-of-scope routing)

## Queue

| # | Finding | Severity | Origin (review type, round) | Routing reason | Status |
|---|---|---|---|---|---|
| 1 | <description + file/location> | P0\|P1\|P2\|P3 | <code-review round 2 / analyze / surface-audit> | <why out-of-scope: not required for the frozen intent's outcomes> | open\|user-waived\|promoted |

## Waivers

<!-- One entry per user-waived P0/P1 (decision-audit landing). Keep in sync with
the `waived_by_user` field in code-review.md. -->

- <#> — waived YYYY-MM-DD — rationale: <user's rationale>

## Promotion

<!-- Filled at archive when the queue is non-empty: the successor change (or
explicit decision not to pursue) per finding. -->

- <#> — <successor change name | not-pursued + reason>
