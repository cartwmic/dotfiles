# History step (SKILL.md step 3)

Mandatory. It has a script half and a skill half. It runs before the interview, so the proposals there have leads.

## Script half

`python3 -I <skill dir>/scripts/history_signals.py REPO --rev <snapshot sha> [--scope PATH ...] [--format md|json] [--out FILE]` lists, read from that commit and not the working tree:

- commits whose subject says fix, revert, perf, security, race, timeout, crash or flaky: sha, date, subject, files. The keyword match only picks leads; a commit it misses may matter, and one it picks may not;
- high-churn files that still exist;
- merged PRs, kept only when their merge commit is an ancestor of the rev, and issues created by the rev's commit time, via `gh` (PRs have no date cut: ancestry is the filter) (the section says why when `gh` does not work, and how many `gh` returned and whether its cap was hit; GitHub search returns at most 1,000 per query, so the script splits the date range until each query is under it, and the cap is hit only when a single day holds that many).

The script cuts nothing by default (the owner asked for any history, and the skill never silently samples). `--limit N` cuts each list to its N newest rows and prints `(M more rows cut by --limit)`; a cut list is a sample, so rerun without it, or say in the report which list you cut and why. When the report is long (hundreds of lines), pass `--out FILE` and read the file in parts, all of it. Put the rev you ran it at in the header `history:`.

In a scoped run pass the scope paths: only history that touches them is listed. The `repo-wide: yes` run gets the other runs' scope lists from the caller, runs the script unscoped, and also takes the signals that touch none of those scopes. A signal whose code lies in another run's scope belongs to that run. `--scope .` means the whole repo; an absolute path inside the repo is accepted. A folder with no git prints "no git history". `docs/snapshots/` is skipped.

Whether a row's code still exists is decided by today's code at the snapshot commit, not by the signals: drop a row whose code is gone and say so.

## Skill half

Read the list as leads, not rows. Before writing a row, open the commit diff or the PR body, and the issue text. Then:

- one row per behaviour, not per commit;
- when a signal belongs to a behaviour you already have a row for, add its ref to that row's `evidence`; do not write a new row;
- write a row only when you conclude the behaviour should be an obligation. Its kind comes from the kind rule in output-shape.md: when a doc, test, issue or the owner states it, the row is `explicit` and the signal is extra evidence.

Patterns worth a row:

- a fix, regression or revert commit: the behaviour it restored;
- commits that keep re-touching one behaviour: it is harder than it looks, or under-specified;
- incident, perf or security fixes: usually a `quality` row;
- PR bodies and review comments, issues, ADRs, changelogs and docs that describe intent without obliging.

For each row set `lens` and `durability` (`unclear` plus a Q when you cannot tell; a one-off typo fix is no row), `kind: inferred`, `status: proposed`, and evidence: the `commit:`, `pr:` or `issue:` refs, and the `path:line` where it lives today when there is a line. History-only evidence is allowed for a quality requirement with no single line. Then judge `check`, `fit` and `enforced` against today's code.

Report only the history rows that changed your view of the repo; a long list of obvious ones is noise. A ref that resolves proves the commit, PR or issue exists, not that it says what the row says.
