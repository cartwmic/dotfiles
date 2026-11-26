# Interview: non-functional requirements

Optional. Run it only in a session that can ask the owner, or when an answers file is given. Before asking, the session that asks runs `history_signals.py` and skims the code for timeouts, limits, retries, retention and auth settings; when a caller runs the interview and hands the file to a subagent, the caller does this. It runs after the history step and before the rest of the distilling, in the session that can ask. A subagent that cannot ask takes the answers file as an input and sets `interview:` to its path.

## How to ask

- Ask at most 4 questions at a time. Each question stands alone, so the owner can answer one without the others.
- Ask every area in the bank, including those with no signal: that is where unwritten requirements live. With no signal, propose nothing and ask open.
- State each proposal as a solution-neutral outcome requirement, the way the owner would say it: "Owner messages and events are delivered at least once, idempotently, and survive crashes and outages". Put at most one short evidence pointer after it. Do not list mechanisms (file names, a test file, a version pin, user ids): owners reject those as overly specific.
- The owner confirms, corrects or skips each proposal. A skipped question makes no row.
- A confirmed or corrected answer becomes an `explicit` row, status `accepted`, evidence `owner:interview <YYYY-MM-DD> Q<n>`. When the owner confirms a requirement you had inferred from history, that row becomes `explicit` and `accepted`, gains the `owner:` evidence and keeps its history refs.
- The owner's intent can differ from the code (for example the owner says identity is authenticated via PGP, and the code does not). Keep the answer: write the row as `disputed` with a Q, or add a finding. Never drop the answer because the code disagrees.
- Scope: in a scoped run, ask only what bears on the scope. Answers about the whole repo go to the run with `repo-wide: yes`.

## Question bank

One question per area; reword to the repo.

| area (lens `quality`) | question |
|---|---|
| performance | How fast must the main operations be, for how much data or load? |
| reliability and availability | What must survive a crash, a retry or an outage, and what may be lost? |
| security and privacy | What data is sensitive, and who may read or change it? |
| maintainability | What must stay easy to change or test? |
| operability and observability | What must an operator see or do when it breaks? |
| portability | Which platforms, versions or hosts must it run on? |
| compatibility | What must stay compatible across versions: data, interfaces, and the order in which parts are deployed? |
| cost | What is the budget for compute, storage or paid calls? |
| data retention | How long is data kept, and how is it deleted? |

## Answers file

Save it as `interview.md` in the caller's output folder, next to `REQUIREMENTS.md`, with the date. One entry per question, numbered from Q1:

```text
# Interview answers
date: 2026-11-26
repo: <name>
commit: <full sha>

Q1 (performance): <question>. Proposed: <outcome requirement> (<one pointer>). Answer: confirmed | corrected: <text> | skipped.
```

A later run may take the file. Its rows are `accepted` "in the interview on <date>" (say so in `note`). When the file's `commit` differs from the snapshot commit, the header's `interview:` says so (`<path> (answers at <sha7>)`). The file is a record of that day, like the snapshot it feeds.
