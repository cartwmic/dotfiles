Seat: lead (skill writer), Opus 5.5 medium (the lister). You have not seen the guide, and you must not look for it: open nothing outside the repo, and no `GUIDE.md` or derived-docs folder.
Lister brief, version 1.

List the facts a newcomer must know to use or work on this repo, taken from the code. Input: the repo path, and your output path (`facts.txt`).

What to list, by kind (the kind names are the ones the file takes):

- `purpose`: what the product is for, and who runs it.
- `run`: how to install, start and use it: each command or step, the one a person types first above all.
- `setting`: each setting a person can change (flag, environment variable, config key, constant they can set), with its default and unit.
- `limit`: each cap, timeout, size, count or rate the code enforces, with its number and unit.
- `failure`: what happens when an input is bad, a dependency is down, a time runs out or a file is missing: the result the code gives (an error, a retry, a skip, an exit code).
- `flow`: each main thing the product does from start to finish, in the order its code runs it.
- `interface`: each command, route, event, export or file format another person or program touches, by the name the code spells.

How to list:

- Read the code, not only the README. The README tells you what to look for; the fact comes from the code line. Open the code that defines each fact: the function, the table, the default.
- One fact on one row, stated in one plain sentence of at most 25 words, with its value, default, limit, unit and failure result when it has them. A fact a reader could not check against one place in the code is two facts or no fact.
- Every row cites the code line that shows the fact (`path:START-END`, the smallest range that shows it, relative to the repo root). Read the lines first: a row citing a line you did not read is wrong.
- Cover the whole repo in proportion: more rows for a capability a user meets often, none for an internal helper nobody touches. Write at most 100 rows (the script refuses more): aim for 60 to 100; under 30,000 lines of code, 30 to 60. When you have more, keep the ones a newcomer needs most. A repo with a handful of settings lists every one of them.
- Mark a fact `core` when a newcomer reading only the first page must have it: what the product is for, how to install and start it, its main flows and its main interfaces. At most 20 rows are `core`; the rest are `detail`.
- Add no security, privacy or threat topic of your own.

Output: a file of rows, one a line, and nothing else but blank lines and lines starting with `#`:

`F<n> | core or detail | kind | the fact | path:START-END`

Numbers run from F1 with no gap. The lead's script rejects a row of another shape and a row that cites a line the repo lacks, so check your own cites before you finish.
