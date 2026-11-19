# Drafting a section: assert-first, then a written audit

For the section writer: a fresh session that drafts one section of a doc. The lead's brief (last part of this file) names the section, its points and files, and your work folder. Why this method: in a lab, one fresh writer per section using it had 4.6% (coordinator) and 3.7% (agent-kit) of claims wrong on the first pass, against about 16% for one whole-repo writer. The lab had no control run, so some of the drop may come from the scoping alone. Most errors left were a sentence true on one path of a function and false on another, so the audit uses the exits that `check_citations.py --sheet` lists.

Keep your work files in your work folder. They are not part of the draft and are never cited. Step 8 (fresh checkers) is not yours; the audit below is your own pass, so the checker finds nothing.

## Stage 1: evidence file (`work/evidence.md`)

For every test, journey or scenario you will cite, open its body and its helpers and write one row per assert/expect line:

| row | `path:line` | compared expression, verbatim | input or trigger, and who ran it | expected value, verbatim | fixture? | code that defines the rule |

- **Compared expression**: copy the expression the line evaluates and the value it is compared with. Do not copy the assert's failure message, the test title or a comment into this column: those labels may say more than the line compares. If the line compares only a count, a length, an includes, or the existence of a row, write that.
- **Who ran it**: the product code, or the test's own scaffolding (a scripted model turn, a stub, a double, a helper script, a hand-written fixture). A thing the scripted side does is not product behaviour. If a rerun differs from the first run in any argument, say so: it is not "the same command".
- **Fixture?**: yes when the input or expected value is the test's own choice (a name, a count, a pid, a path, a message text, a time); no only when the code defines the value.
- **Code that defines the rule**: open the whole function or command the test exercises, not only the cited lines, and write its conditions: flags, branches, early exits, skipped inputs, other callers, other values. Before you have a draft there is no sheet; `python3 -I <skill dir>/scripts/early_exits.py <file> <line>` lists the exits above a line of a function. Write "not read" if you did not open it. A row marked "not read" can only back a sentence worded "in the test".

Then add one line per behaviour you plan to describe, naming the rows it rests on.

## Stage 2: draft

1. Each sentence restates one or more evidence rows, with their conditions, and says no more than those rows show. Write it from the rows, not from your memory of the test.
2. One behaviour per sentence. Name the case in the sentence: "when X, Y".
3. A sentence on a fixture row gives the value as an example ("in the test", "for example"), not as the rule.
4. Copy numbers, names, flags, messages and the place a result appears (standard output, the log, the exit code) from the asserting line, not from memory or a summary.
5. A sentence that says a thing happens in the product (not "in the test" or "in the journey") needs a code row with its conditions, and states each condition. What a key, file, value or event is comes from its definition and its users.
6. Say who did something only as the row's "who ran it" shows. A scripted turn is "in the journey, the scripted turn ...".
7. Words that exist only in a failure message, test title, comment or README stay out, or carry the label "(test title)", "(code comment)" or "(README)" when the code agrees.
8. No "all", "every", "none", "only", "always", counts or full lists unless the code row defines the whole set.
9. Cite directly after the sentence the assert lines and the code lines it rests on, as `SKILL.md` requires. "No test covers X" only after you grep the tests for X.
10. Do not drop a behaviour the points prove to avoid a risk: narrow it. Do not pad: do not split one behaviour into thin sentences.
11. Write for a person. The sentences stay narrow, each with its own citation, but lay them out as short paragraphs or list items grouped by what the reader wants to know, not as one claim per line where that hurts reading. Do not merge two behaviours into one sentence to save space.

Then load `no-ai-slop` (Skill tool) and apply it in edit mode to the draft, keeping every citation, number and name as written. Load its voice profile only when the lead's brief says the docs are the owner's own writing. Put the `Voice:` line in your report. Run `python3 -I <skill dir>/scripts/check_citations.py draft.md <repo>` (no `--points`) and fix every FAIL.

## Stage 3: audit (`work/audit.md`)

Run the same command with `--sheet`. It prints each sentence with its cited lines, and under them the function's early exits above the last cited line: each `return`, `throw`, `continue`, `break` or `exit` that skips the cited code (a `continue` or `break` counts when its loop overlaps the cited lines). An exit marked `[inside the cited lines]` is one of the lines you cite: the sentence states its condition, or you narrow the cited range and the sentence to the lines before it. "No early exits" means none were found; "not listed" means the script could not read the file, so read the function yourself.

Go through the sentences in order, one at a time. For each, re-open its cited lines in the sheet, and the code around them when the sentence says what the code does. Only then write its line:

`N | assert: path:line "<the compared expression, copied from that line>" | exits: <each exit the sheet lists, as "path:line stated" or "path:line off the path: why", or "none listed"> | found: <what the questions below turned up, or "nothing"> | result: HOLDS / narrowed to "..." / cut`

The assert must be one of the sentence's own citations, and its text must read as it does on that line. A line that repeats the one above with a few words changed, or that names no assert, has not been audited. For a sentence that says what a function does, every exit above the cited code must be stated in the sentence or be off its path; an exit you cannot place means you narrow the sentence to the test's case.

The questions, as a fresh checker asks them (`references/check-brief.md`). Be the harsher reader:

- A. An overreach word, count or full list, or "cannot", "is refused", "falls back"? Did you open the whole defining code?
- B. A condition, flag or branch the code has and the sentence lacks?
- C. A value or input that is only the test's own, said as the rule?
- D. Do the cited lines hold the asserting expression, and does it compare everything the sentence says? Read the expression, not the message.
- E. Who acted, the product or the scripted side?
- F. A comment, title or README that needs a label? A negative claim you did not grep?
- G. What a thing is, read from its definition?

When any answer is "no" or "not sure", edit the sentence now: narrow it to what the lines show, add the missing condition, add the line that does show it, or cut it if no narrower true sentence exists. Audit the edited sentence again. Stop when every line says HOLDS. A sentence you edited, or that no-ai-slop reworded, is audited again. Run the check without `--sheet` once more on the final draft; the draft that passes is the one you hand over.

## Briefing a section writer (the lead)

Start one fresh session per section; never one session for the whole repo. The brief's first line names the seat and model the caller's table gives writers. Give it:

- The section: doc type (PRD, DESIGN or SPEC), the heading, and the style that doc needs (see `SKILL.md`).
- Its scope: the points it covers (ids from `points.json`) and the files they and the code they run sit in. Name topic and files only; do not paste earlier text or checker findings.
- The paths: the repo (read only, at the commit), `points.json` and `left-out.txt`, this skill's folder, and the one folder the writer may write in (`draft.md` and `work/`).
- The method: read this file, and `SKILL.md` for the citation form and the rules for every sentence.
- Limits: no subagents, no step 8, no `--points` on the check (a section has no header or counts), no security or privacy language, read only the repo's tests, journeys and code (not its docs), change nothing in the repo.
- The report to send back: path of `draft.md`, number of sentences, the `Voice:` line, and in at most five lines what it could not cover or cut.
