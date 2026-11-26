# Loop engine, target, after the fixes (hand-written example; the path:line evidence is invented)

## FRs
| id | text | dp |
|---|---|---|
| FR6 | recover stuck runs | DP6 |
| FR1 | keep a run's record intact across crashes | DP1 |
| FR2 | advance a run only on evidence-backed verdicts | DP2 |
| FR3 | let a driver add context and evidence | DP3 |
| FR4 | let people see state and history | DP4 |
| FR5 | run externally defined workflows | DP5 |

## DPs
| id | text | parts |
|---|---|---|
| DP1 | append-only run journal | src/journal.py |
| DP2 | verdict gate | src/gate.py; src/runs.py |
| DP3 | evidence submission endpoint | src/api.py |
| DP4 | status and history view | src/view.py; src/runs.py |
| DP5 | workflow loader | src/workflow.py |
| DP6 | stuck-run sweeper | src/recover.py; src/runs.py |

## X
| fr | dp | reason | evidence |
|---|---|---|---|
| FR2 | DP1 | the gate reads verdicts by journal record shape, so a new journal format breaks it | src/gate.py:41; F-2 |
| FR4 | DP1 | the view replays the journal, so a format change changes what people see | src/view.py:17 |
| FR6 | DP1 | the sweeper finds stuck runs from the last journal record | src/recover.py:30 |
| FR2 | DP5 | workflow files define which verdicts count, so a loader change shifts the gate | cochange:src/workflow.py+src/gate.py |
| FR3 | DP2 | the submission endpoint rejects evidence the gate would not accept; gate rules change it | src/api.py:58 |
