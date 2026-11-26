# Interview: non-functional requirements

Optional. Run it only in a session that can ask the owner, or when an answers file is given. It runs before the distilling, in the session that can ask; a subagent that cannot ask takes the answers file as an input and sets `interview:` to its path.

## How to ask

- Ask at most 4 questions at a time. Pick the areas the repo has signals for; skip the rest and say so in the answers file.
- Each question carries a proposed answer drawn from what you found so far (a doc line, a config value, a commit), with its source. The owner confirms, corrects or skips it. Never ask a bare question the repo already answers.
- A skipped question makes no row. A confirmed or corrected answer becomes an `explicit` row, status `accepted`, evidence `owner:interview <YYYY-MM-DD> Q<n>`.
- Scope: in a scoped run, ask only what bears on the scope. Answers about the whole repo go to the run with `repo-wide: yes`.

## Question bank

One question per area; reword to the repo. `Q<n>` numbers are those of the answers file.

| area (lens `quality`) | question |
|---|---|
| performance | How fast must <the main operation> be, for how much data or load? Proposed: <a timeout, benchmark or fix commit found>. |
| reliability and availability | What must survive a crash, a retry or an outage, and what may be lost? Proposed: <a lock, queue, retry or restart behaviour found>. |
| security and privacy | What data is sensitive, and who may read or change it? Proposed: <an auth check, secret handling or redaction found>. |
| maintainability | What must stay easy to change or test? Proposed: <a layering rule, a boundary test or repeated fix area found>. |
| operability and observability | What must an operator see or do when it breaks? Proposed: <a log, metric, health check or runbook found>. |
| portability | Which platforms, versions or hosts must it run on? Proposed: <a CI matrix, manifest or `cfg` found>. |
| cost | What is the budget for compute, storage or paid calls? Proposed: <a quota, cap or paid API found>. |
| data retention | How long is data kept, and how is it deleted? Proposed: <a TTL, cleanup job or schema field found>. |

## Answers file

Save to `interview.md` next to `REQUIREMENTS.md`, with the date. One entry per question, numbered from Q1:

```text
# Interview answers
date: 2026-11-26
repo: <name>
commit: <full sha>

Q1 (performance): <question>. Proposed: <proposal> (<source>). Answer: confirmed | corrected: <text> | skipped.
```

A caller that starts a later run gives this path. The file is a record of that day, like the snapshot it feeds.
