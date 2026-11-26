# History step (SKILL.md step 4)

Mandatory. It has a script half and a skill half.

## Script half

`python3 -I <skill dir>/scripts/history_signals.py REPO --rev <snapshot sha> [--scope PATH ...] [--format md|json]` lists, read from that commit and not the working tree:

- commits whose subject says fix, revert, perf, security, race, timeout, crash or flaky: sha, date, subject, files;
- high-churn files that still exist;
- deleted paths (a rename is not a deletion): skip any row whose code was only there, and name it in the report;
- merged PRs with number, title and labels, when `gh` works in the repo (the section says why when it does not).

In a scoped run pass the scope paths: only history that touches them is listed. A `repo-wide: yes` run also reads history that touches no other scope.

## Skill half

Read the signals with the repo's docs, ADRs, changelogs, `gh pr view` and `gh issue view` text, and propose `inferred` rows, functional and non-functional. Signals worth a row:

- a fix, regression or revert commit: the behaviour it restored is the requirement;
- commits that keep re-touching one behaviour: it is harder than it looks, or under-specified;
- incident, perf or security fixes: usually a `quality` row;
- PR titles, bodies and review comments, and issues: stated intent without a "shall";
- ADRs, changelogs and docs that describe intent.

For each row, set:

- `lens` and `durability` (`unclear` plus a Q when you cannot tell; a one-off fix of a typo is `incidental` or no row);
- `kind: inferred`, `status: proposed`;
- evidence: the `commit:`, `pr:` or `issue:` refs, and the `path:line` where it lives today when there is a line. History-only evidence is allowed for a quality requirement with no single line.

Then judge `check`, `fit` and `enforced` against today's code. A row whose code no longer exists at the snapshot commit is dropped, and the report says so. A history ref that resolves proves the commit, PR or issue exists, not that it says what the row says.
