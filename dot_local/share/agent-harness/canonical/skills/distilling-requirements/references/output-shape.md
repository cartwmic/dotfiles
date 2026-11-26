# REQUIREMENTS.md shape

Read this when writing or reading the file. The file is a snapshot: it records the code at one commit and is never edited afterwards. The headings, table columns and id formats below are the contract; a reader (person or skill) can rely on them. A `|` inside a cell breaks the tables: write `/` instead; a `;` in a test name becomes `,`. Write an id token (`R-1`) only as a real id, never in prose that is not one. Add rows, not columns. If the shape must change, bump `shape:` in the header; `check_shape.py` refuses `requirements/1` and says to rerun the skill.

## Contents
- Header
- 1. Requirements register
- 2. State machines
- 3. Unenforced invariants
- 4. Findings
- 5. Open questions (Q-n)
- Run log

## Header

The file starts with this fenced block of `key: value` lines; the title goes below it, and the first line under the title is fixed text:

```text
shape: requirements/2
repo: <name>
commit: <full sha>
snapshot: <YYYY-MM-DD> at <full sha>
scope: <whole repo | path list; callees and callers read in part as path (lines)>
repo-wide: <yes | no>
interview: <path to the answers file | none>
source: <git | archive>   (optional; archive means no history: write `no-git` for the sha in `commit:` and `snapshot:`)
date: <YYYY-MM-DD>
not-read: <paths or areas skipped, or "none">
counts: R=<n> SM=<n> I=<n> U=<n> F=<n> Q=<n>
```

```text
# Requirements: <repo>

Snapshot of <repo> at <sha7> on <date>. Not maintained: it records the code at that commit, not today's.
```

- `snapshot:` repeats `date:` and `commit:`; `check_shape.py` checks the line under the title word for word against the header (`<sha7>` is the first 7 characters of `commit:`).
- `repo-wide: yes` means this run also took the interview answers and the history that touch no other scope. When several scoped runs cover one repo, the owner or caller names exactly one of them `yes`; a run with no scope is `yes`.
- `interview:` names the answers file (`interview.md`, next to this file) the run used, or `none`; a row with `owner:interview` evidence needs a file here, not `none`.
- Ids are unique within this file. There is no continuity across snapshots: `R-3` in one snapshot need not be `R-3` in the next.
- Where the file lives. Default: a scratch folder outside the repo. Never a root-level `REQUIREMENTS.md`, `GUIDE.md` or `DESIGN.md` in a repo: it looks live. To keep it, write `docs/snapshots/<YYYY-MM-DD>-<sha7>/REQUIREMENTS.md` in the repo, or the same folder name elsewhere.

## 1. Requirements register

One row per requirement. Ids `R-1`, `R-2`, ... unique within this file.

| id | lens | kind | durability | status | requirement | evidence | check | fit | enforced | note |
|---|---|---|---|---|---|---|---|---|---|---|

- `lens`: `product` | `behavioral` | `technical` | `quality`. `technical` is a constraint the code depends on (runtime, schema, layering, interfaces). `quality` is a non-functional requirement: performance, reliability and availability, security and privacy, maintainability, operability and observability, portability, cost, data retention
- `kind`: `explicit` (a stated source) | `implicit` (only the code shows it) | `inferred` (proposed from history or documents that state intent without a "shall": fix, regression and revert commits, a behaviour re-touched again and again, incident, perf or security fixes, PR titles, bodies and review comments, issues, ADRs, changelogs. It is neither stated as an obligation nor shown only by the code). An inferred row has status `proposed`, and `check`, `fit` and `enforced` are judged against today's code like any row
- `durability`: `enduring` | `incidental` | `unclear` (with an open question). A surface that is only incidental (a test fixture's env name, a debug flag) still gets a row marked `incidental` that cites it, so `surface_coverage.py` stops listing it
- `status`: `proposed` (default) | `accepted` (the owner accepted it during this run, for example in the interview; only the owner sets this, and the row needs `owner:` evidence) | `disputed`
- `requirement`: one observable sentence, "shall" form, no implementation words unless the implementation is the requirement
- `evidence`: a `;`-separated list of `path:line`, `commit:<sha, 7+ hex>`, `pr:<number>`, `issue:<number>` and `owner:<source>` parts, mixed as needed. An owner statement with no file line is `owner:<quoted source>`; an interview answer is `owner:interview <YYYY-MM-DD> Q<n>`. An inferred row also cites the `path:line` where the requirement lives today, when there is one; history refs alone are allowed for a quality requirement that has no single line. `check_history_refs.py` resolves the history refs; one that resolves is "resolved, claim not read-checked": it shows the commit, PR or issue exists, not that it says what the row says
- `check`: `path::test name`, `;`-separated, at most three then `+N more`; or `none`
- `fit`: `full` | `partial` | `none` | `title` (judged from the check's name only; its body was not read). For `partial`, `note` says what the check leaves unasserted. A row with several checks takes the weakest: `title` if any check's body was not read
- `enforced`: `yes` | `partial` | `no`. Whether the code itself makes the requirement hold (type, validation, constraint, guard), as opposed to convention or caller discipline. A requirement can be enforced but untested, or tested but unenforced. For `partial` or `no`, `note` says what is not enforced. A `disputed` row, or `durability: unclear`, cites a `Q-<n>` in `note`

## 2. State machines

One subsection per machine, `### SM-<n>: <name>`, then these fields, each a bullet that starts `- ` (`check_shape.py` refuses a `writers:` line without it):

- `where:` the `path:line` of the state field or enum
- States: a table `| state | meaning | evidence |`
- Invariants: a table `| id | invariant | enforced by | evidence |` with ids `I-<n>`, where `enforced by` is `type` | `check` | `constraint` | `convention` (callers keep to it, nothing enforces it) | `test` | `none`; or the line `- Invariants: none found`
- Transitions: a table `| from | event | guard | to | effects | evidence |`; `*` allowed in `from`; write "except X" in `guard` for any state but X
- `writers:` each process or caller that writes the state, and whether it passes a stale-write guard (the read-then-write races come from here)
- `unreachable-by-design:` states or transitions the code forbids, if any

Keep an invariant here, not also in the register; an `R` row may cite its `I-<n>` in `note`.

## 3. Unenforced invariants

Ids `U-<n>`.

| id | invariant relied on | relied on at | missing guard | violation reachable | evidence |
|---|---|---|---|---|---|

`violation reachable`: `yes` (with the path) | `no` (why) | `unknown`. A reachable one that does harm also gets an `F` row citing the `U` id.

## 4. Findings

Reachable invalid states or transitions and other confirmed defects. Ids `F-<n>`, sorted by impact then id.

| id | machine/ref | impact | confidence | path to it | evidence | proposed regression test | issue group |
|---|---|---|---|---|---|---|---|

- `impact`: `high` (wrong data, lost work, stuck) | `medium` | `low`
- `confidence`: `confirmed` (reproduced or unambiguous path) | `likely` (code path certain, external behavior assumed) | `suspected`
- `machine/ref`: ids separated by `;` (for example `SM-1; R-19; U-2`)
- `path to it`: the numbered steps, including any retry or concurrent writer
- `issue group`: a short label shared by findings with one fix

## 5. Open questions

Ids `Q-<n>`, each line naming the ids it blocks, for the owner to settle: `- Q-1: <question>. Blocks R-19, F-1.`

## Run log

Dated lines: what changed during this run only, such as truth-check fix rounds, and which ids; rows dropped because their code no longer exists at the snapshot commit. It is not a history of the file: the file is never edited after the run.
