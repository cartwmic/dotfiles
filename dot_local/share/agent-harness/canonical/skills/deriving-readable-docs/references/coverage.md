# Coverage (steps 8, 12 and 16 of SKILL.md)

Recall is: of the facts a newcomer must know, how many the guide states. Precision is the checkers' job (steps 10 and 13). This file adds the recall side. The lister makes one list of facts; every grade in the run uses that same list, so the figures compare. Keep each run's files in the work folder: `facts.txt`, `grades-<label>.md`, and what `coverage.py` writes (`coverage-<label>.json`, `coverage-<label>.todo.md`, `coverage.md`, one row for each label). A label already recorded is refused.

`<facts>` and `<grades>` below are `facts.txt` and `grades-<label>.md` in the work folder.

## Grade a guide (steps 8, 12 and 16)

1. Once per run, step 8 only: one fresh Opus lister session, briefed with `references/coverage-lister.md`, the repo path and the work folder. It sees the repo and not the guide. It writes `facts.txt`. `python3 -I <skill>/scripts/coverage.py --facts facts.txt <repo>` stops on a malformed row, a repeated id or a row whose cited line the repo lacks: send the file back to the lister before any grader starts.
2. One fresh Opus grader session for each grade, briefed with `references/coverage-grader.md`, `facts.txt`, `GUIDE.md` and the repo. It writes `grades-<label>.md`. A grader is never the lister, and never a writer of the guide.
3. `python3 -I <skill>/scripts/coverage.py <facts> <grades> GUIDE.md <repo> --label <label> --work <work>`. Labels: `first` (step 8), `repair` (step 12), `final` (step 16). It counts COVERED, PARTIAL and MISSING (a quote that is not in the guide turns the row into MISSING), suggests an appendix section for each fact, and writes the to-do.

## The to-do (steps 8 and 12)

The to-do lists each PARTIAL and MISSING fact, grouped by the appendix section whose citations name the same file, then the core ones for Part 1.

- **Appendix.** One fresh Opus writer for each section the to-do names, briefed as the end of `references/drafting.md` says for a section writer, with the to-do rows in place of a capability and 25 words for each fact as its budget. It writes only the new and changed lines in `cov-A<n>.md` (heading `## A<n> <title>`), through Stages 1 to 3 of drafting.md, with its own `work/` files. A PARTIAL fact: the changed line keeps the old line's id, and says what the old line lacked. A MISSING fact: a new line, or a row of the `### Defaults and limits` or `### When things fail` table when it is a setting, limit or failure result. Then the writer puts each line in the section file: a prose line before the section's first `###` block, a row inside its table, a changed line over the old one, and runs `stamp.py` on the section file. It adds nothing the to-do does not name.
- **Part 1.** After the appendix lines are in (`assemble.py <work> <repo> --index` lists their ids), one fresh Opus front writer, briefed as the front writer of drafting.md, adds for each core fact one plain sentence of at most 18 words to the right section of `part1.md`, tagged to its appendix line, while Part 1 has room (the to-do says how many words are left). A fact that does not fit stays in the appendix only. The to-do's core rows are the only ones that get a Part 1 sentence.
- **Guard.** `assemble.py <work> <repo> -o GUIDE.md --clean`, then `lint_main.py`. A coverage sentence that pushes Part 1 over 1,000 words or fails a lint check is fixed once by the front writer, then dropped: its fact stays in the appendix, and Part 1 keeps only the core facts it can say in plain words. Do not shorten the other Part 1 sentences to make room. The reader check (step 14) still gates.

Add no security, privacy or threat language: the lister, the writers and the grader are told so in their briefs.

## Repair (steps 12 to 15)

Step 12 grades the draft that survived the fix rounds (label `repair`, the same `facts.txt`, a fresh grader) and works the to-do as above. Step 13 then checks the whole guide, the lines step 12 added included. The target is 98% of facts COVERED, and 98% of checked claims HOLDS. Step 16 grades again (label `final`) after the last cut and adds nothing: its figures are the ones the report quotes. A final below 98% is reported with its to-do file; the caller decides on another pass.

## The full check (step 13)

Cut the whole guide into slices as step 10 does, checkers with `references/check-brief.md`, reports in `reports-full`, scored against `slices-full`. Keep the copy of the guide the checkers saw as `GUIDE.full.cut.md`. Fix each finding in the section files and `part1.md` (not in `GUIDE.md`, which `assemble.py` writes again) by the repair rule in `references/fix-rounds.md`, then run `assemble.py`, `check_citations.py` and `lint_main.py`. Nothing re-checks those fixes until step 15.
