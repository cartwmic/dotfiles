# Extend an existing guide (passes 2 and 3 of SKILL.md)

Pass 1 is the procedure of `SKILL.md`, unchanged. An extend pass takes the repo and the guide the earlier pass shipped, and adds what that guide misses without adding errors. A line that is unchanged since the earlier guide is not rewritten, so a pass can add errors only in the lines it writes. At most 3 passes in all: pass 2 extends pass 1's guide, pass 3 extends pass 2's.

## Inputs and folders

- The repo, the earlier `GUIDE.md`, and an output folder `<out>` (one per pass).
- `<out>/GUIDE.was.md`: a copy of the earlier guide, never edited. `<out>/GUIDE.md`: the same text, edited in place by the steps below. The earlier guide is a shipped file (pass 1 cut it in place), so there are no section files: `assemble.py` is never run, and the lines are put into `GUIDE.md` itself.
- `<out>/surfaces.json` from `python3 -I <skill>/scripts/surfaces.py <repo> --json`, for `python3 -I <skill>/scripts/lint_main.py --surfaces`.
- Budgets: Part 1 stays at most 1,000 words. The appendix grows at most about 1,500 words in a pass: `python3 -I <skill>/scripts/coverage.py --grow 1500` works that figure out and prints the `--max-words` value (the guide's words now plus 1,500) that every `check_citations.py` call of the pass takes.
- Add no security, privacy or threat language: the lister, the writers and the grader are told so in their briefs.

## E1 Facts

One fresh lister session (`Seat: lead (skill writer), Opus 5.5 medium`), briefed with `references/coverage-lister.md`, the repo path and `<out>`. It sees the repo and not the guide, and a new lister runs in each pass. It writes `<out>/facts.txt`. `python3 -I <skill>/scripts/coverage.py --facts facts.txt <repo>` stops on a malformed row, a repeated id, more than 100 facts or a row whose cited line the repo lacks: send the file back before the grader starts.

## E2 Grade and fit the to-do

One fresh grader session (`Seat: reviewer (skill checker), Opus 5.5 medium`), briefed with `references/coverage-grader.md`, `facts.txt`, `<out>/GUIDE.md` and the repo. It marks each fact COVERED, PARTIAL or MISSING and quotes the guide line, or each line when several together state the fact. It writes `grades.md`. A grader is never the lister and never a writer of the guide.

`python3 -I <skill>/scripts/coverage.py facts.txt grades.md GUIDE.md <repo> --label extend --work <out> --grow 1500` counts the grades (a quote that is not in the guide is dropped), routes each fact and writes `coverage-extend.todo.md`, `coverage-extend.json` and `coverage.md`. The to-do is cut to the word room: 25 words a fact, core facts first, then MISSING before PARTIAL. Facts that do not fit go under `## Did not fit` and no writer works them.

- A PARTIAL fact is an edit: the to-do names the line (`edit line A4.3f9a in place`) and the writer changes it so it says the fact (the value, unit, default, limit, failure result and the condition it lacked), keeping its id. A PARTIAL fact never gets a second line.
- A MISSING fact is a new line: the to-do names the nearest line of its section that cites the same file (`add next to A4.3f9a`) and the new line goes directly after it, never at the top of the section. When no line cites the file it goes after the section's last prose line.

## E3 Appendix writers

One fresh writer for each section the to-do names, run one after another because they all edit `GUIDE.md` (`Seat: lead (skill writer), Opus 5.5 medium`; briefed as the end of `references/drafting.md` says for a section writer, with the to-do rows in place of a capability, the room's estimate for each row as its budget and a `Files:` line; run `lint_brief.py` on the brief). Each writer:

1. Writes only its new and changed lines in `cov-A<n>.md` (heading `## A<n> <title>`; an edited line keeps its id), through Stages 0 to 3 of drafting.md with its own `work/` files. `work/choice.md` holds the to-do rows it will write and, for each file under `Files:`, the timeout, bad input and down-dependency line of Stage 0, because `python3 -I <skill>/scripts/check_citations.py --audit` wants it.
2. Audits every line (the condition audit below) and runs `python3 -I <skill>/scripts/check_citations.py cov-A<n>.md <repo> --max-row-words <rows x estimate> --max-sentence-words 18 --audit work/audit.md` to exit 0, with `work/choice.md`, `work/guards.md` and `work/evidence.md` beside it. It audits `cov-A<n>.md` only.
3. Puts each line into `<out>/GUIDE.md`: an edited line replaces the line with that id; a new line goes where the to-do names. It changes no other line and adds nothing the to-do does not name.

Then `python3 -I <skill>/scripts/stamp.py --guide GUIDE.md` gives each new line an id (the header and Part 1 are left alone).

**The condition audit.** A coverage line is where a value gets stated without the guard, branch or exception that limits it. For each line, the writer opens the cited line and the whole function around it, lists its early exits, flags, branches and other callers (`python3 -I <skill>/scripts/check_citations.py --sheet`, `--guards`, and the harsher second pass of drafting.md), and each one is stated in the line or the line is narrowed to the case it read. A fact that needs more conditions than 18 words can carry is split, each part keeping its condition, or narrowed. For an edited line the audit covers the whole line: its old conditions are checked again, and the edit may not drop one.

## E4 Part 1

New Part 1 text is only for core facts of the to-do, and only while Part 1 has room. `python3 -I <skill>/scripts/extend.py index GUIDE.md <repo>` prints the appendix ids and sentences. One fresh front writer (`Seat: lead (skill writer), Opus 5.5 medium`), briefed as the front writer of drafting.md with the index, the to-do's core rows and the words left, adds one plain sentence of at most 18 words for each core fact, tagged to its new or edited appendix line, in the right section of Part 1 in `GUIDE.md`. It rewords no other Part 1 sentence. It writes `work/part1-audit.md` by hand, one row for each sentence it adds: `<its tag> | the tagged line says: <value, conditions, labels> | the sentence says: <the same, as worded> | result: HOLDS / narrowed to "..." / dropped`. Every condition and label the tagged line states is in the sentence, or the sentence is narrowed, or dropped.

## E5 Gate

1. `python3 -I <skill>/scripts/check_citations.py GUIDE.md <repo> --max-words <the figure coverage.py printed> --max-sentence-words 18` exits 0.
2. `python3 -I <skill>/scripts/lint_main.py GUIDE.md <repo> --surfaces surfaces.json`. A coverage sentence that fails it, or pushes Part 1 over 1,000 words, is fixed once by the front writer, then dropped with `python3 -I <skill>/scripts/final_recheck.py drop`: its fact stays in the appendix. Do not shorten the other Part 1 sentences to make room.

## E6 Check only the new and changed lines

`python3 -I <skill>/scripts/extend.py diff GUIDE.was.md GUIDE.md <repo> --out slices-new --todo coverage-extend.json` cuts into slices the claims the pass wrote or changed and the ones whose judgment can change with them (the line before a new or edited line, and each Part 1 sentence tagged to a new or edited line). It prints the counts, one `REMOVED` row for each old line the new guide lacks, and exits 1 with a `NOT IN THE TO-DO` row for an old line the writers edited that the to-do did not name: send that back to the writers. `slices-new/context.txt` says why each claim was picked. Keep `GUIDE.md` as `GUIDE.new.cut.md`. When a run repaired the incoming guide first, that repaired copy is the old file (`GUIDE.was.md`) instead, here and in E7 step 4.

One fresh checker per slice (`Seat: reviewer (skill checker), Opus 5.5 medium`), briefed with `references/check-brief.md` as written (the same brief pass 1 uses), its claims file and flags file, reports into `reports-new` (name a Part 1 report `part1-*.md`). `python3 -I <skill>/scripts/score.py new=reports-new --doc GUIDE.md --repo <repo> --slices slices-new` scores them like any pass-1 check.

## E7 Repair before cut

A finding is repaired, not deleted. An OVERSTATED claim or one missing a condition (MISSING_CONDITION) gets the condition the checker names, split past 18 words with each part keeping its condition. A NAME or COUNT finding gets the value or word the code shows. A WRONG claim is rewritten to what the code shows when that helps a reader. Cut a claim only when it is wrong and no true version helps, or when nothing in the cited lines supports it. Edit `GUIDE.md` in place (never run `assemble.py`).

1. `python3 -I <skill>/scripts/final_recheck.py repair GUIDE.md <repo> --ids slices-new/changed.txt --reports reports-new --out repair.txt` lists each failing claim as `fix` (cause MISSING_CONDITION, NAME or COUNT) or `cut`.
2. `python3 -I <skill>/scripts/final_recheck.py cut GUIDE.md <repo> --ids slices-new/changed.txt --reports reports-new --except repair.txt --held-out held.txt --clean` cuts the `cut` claims and writes `held.txt`, the claims the checkers passed.
3. Fix each claim of `repair.txt` once, in place: the lead for an appendix line (keep its id), a fresh front writer for a Part 1 sentence. A condition added to a Part 1 sentence is added to its tagged appendix line too.
4. `python3 -I <skill>/scripts/final_recheck.py changed GUIDE.md <repo> --was GUIDE.was.md --skip held.txt --out changed2.txt` lists every claim still different from the guide this pass extended, that no checker passed as it stands, a passed claim that only moved included. When a run repaired the incoming guide first, that repaired copy is the `--was` file instead, in both commands. One fresh checker per slice (`python3 -I <skill>/scripts/slice.py ... --ids changed2.txt --out slices-new2`; no `--was`: `changed2.txt` already holds every changed claim, and with `--was` slice.py also adds each claim that differs from the old guide, held ones included), then `python3 -I <skill>/scripts/final_recheck.py cut ... --ids changed2.txt --reports reports-new2 --clean`. A repaired claim that still fails is cut now.
5. `check_citations.py` and `lint_main.py` again. A Part 1 sentence that fails (a cut can leave a dangling "unless", or a tag that no longer backs it) goes back to the front writer for one narrowing fix that adds no claim, number or condition; one that still fails is dropped whole with `python3 -I <skill>/scripts/final_recheck.py drop`, which refuses the `Who it is for` sentence and the last How to start step. The shipped guide must pass `lint_main.py`.

## E8 Reader check and report

Follow `references/reader-check.md` on Part 1 of the guide as it now stands: 5 of 5, and `lint_main.py` passes. Its fix round, if needed, is re-checked as in E7 step 4, with the same `--was` file (`GUIDE.was.md`, or the repaired copy). Then `GUIDE.md` and `GUIDE.clean.md` in `<out>` are the pass's guide, and the next pass starts from them.

Report the folder, Part 1 and whole-guide words (and the room used), the `score.py` line for the new and changed claims, the `coverage.md` row, the REMOVED rows, the reader-check result and what was not read.
