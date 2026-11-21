# Agent record: deriving-readable-docs

Branch `readable-docs-recall-climb`, bar `cartwmic/dotfiles = personal`. No PR is open. This file is under `docs/`, which chezmoi does not deploy.

## Coverage pass and repair to 98% (builder, Sonnet 5.5 high)

What changed: a coverage pass in the skill (one lister, one grader, `scripts/coverage.py`, writers who add what is missing), run after round-1 assembly and again on the shipped draft; a full-guide precision check as a repair step; the final grade measured last. Steps are now 1 to 16.

| Step | What | Where |
|---|---|---|
| 8 | Coverage (first): lister, grader, `coverage.py --label first`, writers add, assemble and gate again | `SKILL.md`, `references/coverage.md` |
| 12 | Coverage (repair): fresh grader, same `facts.txt`, `--label repair`, add what is missing | same |
| 13 | Full check of the whole guide, repair rule (add the condition; cut only a wrong claim no true version helps), `GUIDE.full.cut.md` kept | `SKILL.md`, `references/fix-rounds.md` |
| 15 | Final re-check, `--was GUIDE.full.cut.md`: every new or changed line, coverage lines included | `SKILL.md`, `references/fix-rounds.md` |
| 16 | Final grade (`--label final --min 98`), then report | `SKILL.md` |

New files: `scripts/coverage.py`, `references/coverage.md`, `references/coverage-lister.md`, `references/coverage-grader.md`, `tests/deriving-readable-docs/test_coverage.py`.

### Proof

| Claim | Evidence | Kind |
|---|---|---|
| The skill's tests pass | `python3 -I -m unittest discover -s tests/deriving-readable-docs -p 'test_*.py'`: 539 tests before, 591 after (52 new, all in `test_coverage.py`), OK | ran |
| `coverage.py` turns a grade file into a to-do and a record | dry run on a hand-made repo, facts and grades (one grade row with a note after the quote): `first: 5 facts, covered 1, partial 1, missing 3: 20.0% covered ...`, `BELOW 98%` exit 1, to-do grouped by section with a `Files:` line, the core facts and Part 1 room, `coverage.md` row; a rerun of the same label was refused | ran |
| The new tests can fail | six breaks of `coverage.py` (skip the quote check, allow a label twice, count PARTIAL as covered, parse a grade note into the quote, key sections by heading, keep citations in a quote) each failed the tests; script restored | ran |
| Bugs found by driving the script with brief-shaped input | a cite to line 41 of a 40-line file passed (trailing newline counted as a line); a grade row with a note after the quote lost its quote; a fact could be sent to a gathered table section that has no file; a quote that left out a mid-line citation did not match. All fixed, each with a test | ran |
| The lister, grader and writer sessions work as written | not run: the briefs and the steps were read and tested for wiring only. A real climb run is the first proof | assumed |
| The Part 1 guard holds on a real guide | not run on a real guide; `coverage.py` reports Part 1 words by `lint_main`'s own count (test asserts the two agree) and the existing `lint_main.py` gate is unchanged | tested, not driven |

The tests ran locally (about 30 s): `kgate.toml` lists only the heavy-gate and workstream-rank suites. GitHub CI's `tests` job (`scripts/ci-linux.sh`) runs `tests/deriving-readable-docs` on a pull request, but no PR is open, so there is no CI receipt yet. This is not a `heavy-gate` job.

### Design principles

| Principle | Result | Evidence |
|---|---|---|
| 1 Composable components | pass | `coverage.py` does one job (facts + grades + guide to to-do and record); other scripts unchanged; reused `claims.py` and `lint_main.WORDS_MAX` |
| 2 Kernel and adapters | pass (n/a) | a stdlib CLI in a skill; no runtime or transport to separate |
| 3 Clean architecture | pass (n/a) | small script: pure functions (`read_facts`, `verify`, `build`, `todo_text`) and one `record` writer; scaled to size per §4 |
| 4 YAGNI and KISS | pass | one script, no merge helper (writers put lines into section files; `assemble.py` already refuses a bad block); `--facts` is the only extra mode and exists to stop a bad list before a grader runs |
| 5 Contracts and invariants | pass | the row formats are written in the script docstring and the two briefs; a label is recorded once; each fact has one row |
| 6 Conformance suites | n/a | no adapters |
| 7 No cross-component imports | pass | imports only the skill's own `claims.py` and `lint_main.py`, as sibling scripts already do |
| 8 Judgment in agents, mechanism in code | pass | what counts as COVERED, PARTIAL or core is decided by the grader and lister prompts; the script counts, checks that quotes and cites exist, and lists |
| 9 Fix the cause; no arbitrary caps | pass | the 1,000-word coverage allowance is a stated budget line (logged), not a cover for a defect; `--min` is the owner's 98% target, an option |
| 10 Good enough (personal) | not cited | no shortcut taken on this basis |
| 11 Prior art | pass | extends the existing checker, `slice.py` and `final_recheck.py` flow; no new library |
| 12 Verified from the outside | partial | script driven through its CLI end to end and mutation-checked; the LLM sessions were not run (see Proof) |
| 13 Intent tensions | pass | the goal "keep Part 1 plain and short while recall rises" is handled by the core-only Part 1 rule, the word room figure and the drop-first rule; the budget conflict is logged |
| 14 Logs that replay | n/a | no acting component; the record (`coverage-<label>.json`, `coverage.md`) lists each grade |
| 15 Fast proof | pass | 52 new tests run in under 1 s; the suite takes about 30 s |
| 16 Built to last | pass | the old "no full final check" test was rewritten, not bypassed; steps renumbered so lists render; every doc that named a step number was updated |

### Harness note (playbook 096ec3a0)

The skill is canonical and is linked into Claude Code, Cursor and Pi by the existing skill link step; nothing here is Claude-only.

Decisions: #5138 #5139 #5140

## Hold first-pass precision, make repair add coverage (builder, Sonnet 5.5 high)

Why: two real runs showed recall rising but first-pass precision falling from about 97% to about 94%, nearly all of it MISSING_CONDITION in lines the coverage writers added. Repair also lost recall (step 15 cut lines one condition would have fixed, a cut left a dangling "unless" that failed `lint_main`, coverage writers duplicated PARTIAL facts), and the to-do (73 rows) was far larger than the word room (38 words). Branch `readable-docs-recall-climb`; no PR is open.

| # | Change | Where |
|---|---|---|
| 1 | Condition audit for every coverage line and every Part 1 sentence a coverage step adds; an edited line is re-audited whole | `references/coverage.md`, step 8 of `SKILL.md` |
| 2 | A PARTIAL fact is routed to the section file and line id that hold its quote (a Part 1 quote, to the appendix line it is tagged with) and is edited in place; a MISSING fact is placed next to the nearest line citing the same file | `scripts/coverage.py`, `references/coverage.md` |
| 3 | The to-do is ranked (core, then MISSING before PARTIAL, then fact number) and cut to the word room at 25 words a fact; the rest go in a "Did not fit" list in the to-do and in `coverage.md`; `--budget` is required; the lister is capped at 100 facts, refused by the script | `scripts/coverage.py`, `references/coverage-lister.md` |
| 4 | Step 15 repairs before it cuts: `final_recheck.py repair` splits failing claims into fix (MISSING_CONDITION, NAME, COUNT) and cut; `cut --except` cuts only the unrepairable first; the rest are fixed once in place and re-checked once; `drop` removes a Part 1 sentence that still fails `lint_main` and refuses the Who it is for sentence and the last How to start step; the shipped guide must pass `lint_main` | `scripts/final_recheck.py`, `references/fix-rounds.md`, step 15 |
| 5 | Sessions named by the seat table (scout, writers/lister, checkers/graders/reader) | `SKILL.md`, `drafting.md`, each brief |
| 6 | Exact report row for a table header, `read \| N.k \| HOLDS \| outside`; check brief is now version 10 | `references/check-brief.md`, `scripts/score.py` message |

New tests: `test_coverage_fit.py` (23, items 2 and 3), `test_repair_not_cut.py` (20, item 4), `test_seats_and_audit_docs.py` (11, items 1, 5, 6).

### Proof

| Claim | Evidence | Kind |
|---|---|---|
| The skill's tests pass | `python3 -I -m unittest discover -s tests/deriving-readable-docs -p 'test_*.py'`: 591 tests before, 645 after (54 new), OK | ran |
| The new tests fail on the old head | the three new files, with the updated `test_coverage.py` and `test_final_recheck.py` they import, copied into a `git worktree` of `ea31adcf` and run: `test_coverage_fit` FAILED (failures=3, errors=20, mostly `build()` has no budget argument), `test_repair_not_cut` FAILED (failures=17 of 20; the other 3 are the lint fixture and refusals that old code also gives), `test_seats_and_audit_docs` FAILED (failures=11 of 11). Worktree removed after | ran |
| `coverage.py` routes PARTIAL rows and cuts the to-do to the room | dry run on a hand-made repo, facts, grades and guide, `--budget 107` (the guide had 75 words): `first: 7 facts, covered 2, partial 2, missing 3: ...; to-do 1 facts, 4 did not fit (room 32 words)`. The to-do listed F5 (core MISSING) as `add next to A4.cccc (cites src/app.py:20)`; F2, F3, F7, F6 went under `## Did not fit` and into `coverage.md`. With `--budget 7000`: F2 `edit line A4.bbbb in place`, F6 `edit line A4.cccc in place` (the lines that hold their quotes, not the section that cites the file most), F3 `add next to A4.eeee ... a table row`, F7 `add after the last prose line of its section (no line of it cites this file)`. A later label's row still landed inside the table | ran |
| The cut-then-lint failure is rebuilt and cleared | `test_repair_not_cut`: a Part 1 sentence with an "unless" that only a cut appendix line carried passes `lint_main` before the cut, fails it (`absolute`) after, and passes after `final_recheck.py drop`; the repair, in-place fix, re-check, cut order is run end to end on a fixture guide | ran |
| A bare `N` in the brief's header-row line would not be read | `score.parse_rows` accepts only `N.k`; the new row is `read \| N.k \| HOLDS \| outside` (logged as a choice) | ran |
| The lister, grader, writer and checker sessions follow the new text, and precision returns to 97% | not run: no LLM session was started in this job. The next climb run is the first proof. The Part 1 audit rows (`work/part1-audit.md`) have no script check | assumed |

The tests ran locally (about 32 s). GitHub CI would run the same folder on a PR; none is open. Not a `heavy-gate` job.

### Design principles

| Principle | Result | Evidence |
|---|---|---|
| 1 Composable components | pass | `coverage.py` routes and fits; `final_recheck.py` gained two modes (`repair`, `drop`) and one option (`--except`) on its existing cut code; `score.FINDING` and `lint_main` helpers reused |
| 2 Kernel and adapters | pass (n/a) | stdlib CLIs inside a skill |
| 3 Clean architecture | pass | pure functions (`route_partial`, `route_missing`, `rank`, `build`, `repair_rows`, `protected`, `cut_text`) and one writer each |
| 4 YAGNI and KISS | pass | one words-per-fact figure and one budget; no new script; no script check for the Part 1 audit rows (judgment, the lint already gates the guide) |
| 5 Contracts and invariants | pass | row formats in docstrings and briefs; a label is recorded once; the cap of 100 and a required `--budget` are enforced by the script |
| 6 Conformance suites | n/a | no adapters |
| 7 No cross-component imports | pass | imports only sibling scripts, as before |
| 8 Judgment in agents, mechanism in code | pass | the audit and the fix are agent work; ranking, routing, the room, the cap, the repair/cut split and the lint-safe drop are code |
| 9 Fix the cause; no arbitrary caps | pass | no check was loosened; the 100-fact cap and 25 words a fact are stated estimates with an option; the cause of the dropped coverage (a to-do larger than the room) is fixed at its source |
| 10 Good enough (personal) | not cited | |
| 11 Prior art | pass | extends the existing coverage, cut and score code |
| 12 Verified from the outside | partial | scripts driven through their CLIs on hand-made input; the LLM sessions were not run (see Proof) |
| 13 Intent tensions | pass | precision (fewer, audited coverage lines, repair before cut) against recall (PARTIAL edits, core first) is handled by ranking and the audit, not by dropping the recall pass |
| 14 Logs that replay | pass | `coverage-<label>.json` now records the room, the estimate, each row's route and whether it was listed |
| 15 Fast proof | pass | the 54 new tests run in about 3 s |
| 16 Built to last | pass | old tests asserting the replaced wording were rewritten, not removed; `SKILL.md` stays under its length test (1,757 words of 1,760) by moving detail to references |

### Choices a lead should know

- `--budget` is required (no 7,000 default): it halves under 30k lines.
- Step 15 cuts the unrepairable claims first, then fixes the repairable ones in place on GUIDE.md (never through `assemble.py`), re-checks once, and cuts what still fails.
- The check brief's header-row line uses `N.k`, not the brief's literal `N`, because `score.py` reads only `N.k`. The check brief is version 10 (log entry: no verdict rule changed).
- The condition audit for coverage lines is wired through the existing `check_citations.py --audit` command and the written rules; Part 1 additions get a hand-written audit file with no script check.

### Harness note (playbook 096ec3a0)

The skill is canonical and is linked into Claude Code, Cursor and Pi by the existing skill link step; nothing here is Claude-only.

Decisions: #5158 #5159 #5160 #5161
