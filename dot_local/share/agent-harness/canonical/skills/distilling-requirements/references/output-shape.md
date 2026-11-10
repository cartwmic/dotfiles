# REQUIREMENTS.md shape

Read this when writing or reading the file. The headings, table columns and id formats below are the contract; a reader (person or skill) can rely on them. A `|` inside a cell breaks the tables: write `/` instead; a `;` in a test name becomes `,`. Write an id token (`R-1`) only as a real id, never in prose that is not one. Add rows, not columns. If the shape must change, bump `shape:` in the header.

## Contents
- Header
- 1. Requirements register
- 2. State machines
- 3. Unenforced invariants
- 4. Findings
- 5. Open questions (Q-n)
- Changelog

## Header

The file starts with this fenced block of `key: value` lines; the title goes below it:

```text
shape: requirements/1
repo: <name>
commit: <full sha>
scope: <whole repo | path list; callees and callers read in part as path (lines)>
source: <git | archive>   (optional; archive means no history, so no drift check)
date: <YYYY-MM-DD>
not-read: <paths or areas skipped, or "none">
counts: R=<n> SM=<n> I=<n> U=<n> F=<n> Q=<n>
```

## 1. Requirements register

One row per requirement. Ids `R-1`, `R-2`, ... never reused.

| id | lens | kind | durability | status | requirement | evidence | check | fit | enforced | note |
|---|---|---|---|---|---|---|---|---|---|---|

- `lens`: `product` | `behavioral` | `technical`
- `kind`: `explicit` (a stated source) | `implicit` (only the code shows it)
- `durability`: `enduring` | `incidental` | `unclear` (with an open question)
- `status`: `proposed` (default) | `accepted` (the owner accepted it; only the owner sets this) | `disputed`
- `requirement`: one observable sentence, "shall" form, no implementation words unless the implementation is the requirement
- `evidence`: `path:line` list, `;`-separated. An owner statement with no file line is `owner:<quoted source>`
- `check`: `path::test name`, `;`-separated, at most three then `+N more`; or `none`
- `fit`: `full` | `partial` | `none` | `title` (judged from the check's name only; its body was not read). For `partial`, `note` says what the check leaves unasserted. A row with several checks takes the weakest: `title` if any check's body was not read
- `enforced`: `yes` | `partial` | `no`. Whether the code itself makes the requirement hold (type, validation, constraint, guard), as opposed to convention or caller discipline. A requirement can be enforced but untested, or tested but unenforced. For `partial` or `no`, `note` says what is not enforced. A `disputed` row, or `durability: unclear`, cites a `Q-<n>` in `note`

## 2. State machines

One subsection per machine, `### SM-<n>: <name>`, then:

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

## Changelog

Dated lines: what changed, and which ids.
