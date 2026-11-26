# Illustrative example, not a real repo: a loop engine, target, after the fixes

Nothing here describes real code. F-n stand for findings of an imagined requirements register, D-n for decisions of an imagined DESIGN.md: D1 the sweeper reports a recovery as evidence through the endpoint, D2 the sweeper owns its lease timeout.
The FRs are outcomes, none names a module. The DPs do not map one to one onto modules: two parts serve three DPs.

## FRs
| id | text | dp |
|---|---|---|
| FR1 | A run's record survives a crash | DP1 |
| FR2 | A run moves forward only on an evidence-backed verdict | DP2 |
| FR3 | A driver can add context and evidence to a run | DP3 |
| FR4 | People can see a run's state and history | DP4 |
| FR5 | Workflows defined outside the engine run | DP5 |
| FR6 | A stuck run gets recovered | DP6 |

## DPs
| id | text | parts |
|---|---|---|
| DP1 | append-only run journal | journal; snapshot writer |
| DP2 | verdict gate | gate; run state |
| DP3 | evidence submission endpoint | api |
| DP4 | status and history view | view; run state |
| DP5 | workflow loader | loader; schema |
| DP6 | lease-based sweeper | sweeper; lease timeout |

## X
| fr | dp | reason | evidence |
|---|---|---|---|
| FR2 | DP1 | the gate reads verdicts by journal record shape, so a new journal format breaks it | F-2 |
| FR4 | DP1 | the view replays the journal, so a format change changes what people see | F-4 |
| FR6 | DP1 | the sweeper finds stuck runs from the last journal record | F-5 |
| FR2 | DP5 | workflow files define which verdicts count, so a loader change shifts the gate | F-1 |
| FR3 | DP2 | the endpoint rejects evidence the gate would not accept, so a gate rule change changes it | F-6 |
| FR6 | DP3 | the sweeper reports a recovery as evidence, so a change to the endpoint format changes the sweeper | D1 |

## Removed
| fr | dp | by |
|---|---|---|
| FR2 | DP6 | D1 |
| FR6 | DP2 | D2 |
