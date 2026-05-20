# Clarify Findings

<!--
Three passes over the EARS acceptance criteria in specs/**/spec.md.
Each finding ends as a 2-option question. Answer A = keep as-is.
Answer B = change as proposed. Status field tracks resolution.
-->

## Pass 1 — Ambiguity (semantic-entropy lite)

<!-- For each AC, paraphrase 3 times. Divergent paraphrases → finding. -->

| # | AC ref | Question | Option A (keep) | Option B (change) | Status | Resolution |
|---|---|---|---|---|---|---|
| A1 | <spec>:R<n> | <description of ambiguity> | <interpretation X> | <interpretation Y> | unanswered\|answered\|deferred | <user choice + rationale> |

## Pass 2 — Inconsistency (pairwise antecedent overlap)

<!-- For each pair of ACs whose antecedents can hold simultaneously,
check consequents for conflict on a shared observable output. -->

| # | AC pair | Shared antecedent | Conflict on output | Option A (keep both) | Option B (resolve) | Status | Resolution |
|---|---|---|---|---|---|---|---|
| I1 | <R1, R2> | <conjunction> | <output> | <which wins> | <how to narrow> | unanswered\|answered\|deferred | <choice> |

## Pass 3 — Completeness (event/state combination enumeration)

<!-- Enumerate cartesian product of declared events × states.
Each uncovered combination → finding. -->

| # | Combination | Question | Option A (intentional silence) | Option B (add new AC) | Status | Resolution |
|---|---|---|---|---|---|---|
| C1 | <events × states> | <what should the system do?> | <accept as undefined> | <draft AC> | unanswered\|answered\|deferred | <choice> |

## Outstanding (status != answered)

<!-- Auto-populated mirror of findings whose status is unanswered or deferred.
The analyze artifact will copy `deferred` findings into its outstanding-risks
section. Findings with status `unanswered` BLOCK progression to design. -->

- <#: finding summary, status>

## Summary

- Pass 1 findings: <count>; unanswered: <count>; deferred: <count>
- Pass 2 findings: <count>; unanswered: <count>; deferred: <count>
- Pass 3 findings: <count>; unanswered: <count>; deferred: <count>
- **Gate status:** <READY for design | BLOCKED on unanswered findings>
