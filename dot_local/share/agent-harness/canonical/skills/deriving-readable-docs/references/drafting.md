# Drafting a section: assert-first, then a written audit

For the section writer: a fresh session that drafts one section of a doc. The lead's brief (last part of this file) names the section, its points and files, and your work folder. Why this method: in a lab, one fresh writer per section using it had 4.6% (coordinator) and 3.7% (agent-kit) of claims wrong on the first pass, against about 16% for one whole-repo writer. The lab had no control run, so some of the drop may come from the scoping alone. Most errors left were a sentence true on one path of a function and false on another, so the audit uses the exits that `check_citations.py --sheet` lists.

Why a budget: the first run of this method, with no limit, wrote 3,800 claims (88,000 words) for a repo whose earlier draft had 540, and the number of wrong claims went up from 88 to 189. About 6 in 10 of them dropped a condition the code has (a branch, a flag, another caller). You have a word budget: write fewer, better-read sentences.

Keep your work files in your work folder. They are not part of the draft and are never cited. Step 8 (fresh checkers) is not yours; the audit below is your own pass, so the checker finds nothing.

## Stage 0: choose (`work/choice.md`)

Your budget is B words, counted as the check counts them: a word is any space-separated token with a letter, digit or underscore in it, and every such token of the draft counts, headings and backticked names included. Citations, fenced code and bare marks (`-`, `1.`, `##`) do not. A sentence with its citation is about 25 words, so you have about B/25 sentences. From the points in your scope, list the behaviours a reader of this document most needs for your capabilities, one line each, and keep the first B/25. Prefer a behaviour whose rule you can read end to end: the one function or command, its branches stated in one clause. Leave out a behaviour whose defining code has more branches than you can state, or that rests on a test's setup. Points you leave out stay uncited; that is expected. Do not reach the budget by joining two behaviours into one sentence or by generalising ("the command refuses bad input"): drop the behaviour.

## Stage 1: evidence file (`work/evidence.md`)

For each behaviour you kept, and only those, open every test, journey or scenario you will cite, its body and its helpers, and write one row per assert/expect line:

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
5. A sentence that says a thing happens in the product (not "in the test" or "in the journey") needs a code row with its conditions, and states each one that applies: the flag, the input kind, the other caller, the case that returns earlier. The test being one case of the function is the usual miss. What a key, file, value or event is comes from its definition and its users.
6. Say who did something only as the row's "who ran it" shows. A scripted turn is "in the journey, the scripted turn ...".
7. Words that exist only in a failure message, test title, comment or README stay out, or carry the label "(test title)", "(code comment)" or "(README)" when the code agrees.
8. No "all", "every", "none", "only", "always", counts or full lists unless the code row defines the whole set.
9. Cite the line that shows what the sentence names: where a limit is checked, a default is set, a command is called, not the nearby loop, signature or comment. Cite directly after the sentence the assert lines and the code lines it rests on, as `SKILL.md` requires. "No test covers X" only after you grep the tests for X.
10. Narrow, do not stack. When a sentence would need a branch, flag, caller or exception it does not state, narrow the claim to the case you read ("when X, ...", "in the test, ...") or drop it. Do not add clause after clause ("unless A, B or C"): a sentence that needs two "unless" clauses is about the wrong case. Add an exception only when you have read it in the code and cite its line; an exception you did not read is itself a wrong claim. Do not hedge ("usually", "may"), and do not pad or split one behaviour into thin sentences.
11. Write for a person. The sentences stay narrow, each with its own citation, but lay them out as short paragraphs or list items grouped by what the reader wants to know, not as one claim per line where that hurts reading. Do not merge two behaviours into one sentence to save space.

Then load `no-ai-slop` (Skill tool) and apply it in edit mode to the draft, keeping every citation, number and name as written. Load its voice profile only when the lead's brief says the docs are the owner's own writing. Put the `Voice:` line in your report. Run `python3 -I <skill dir>/scripts/check_citations.py draft.md <repo> --max-words B` (no `--points`) and fix every FAIL.

## Stage 3: audit (`work/audit.md`)

Run the same command with `--sheet`. It prints each sentence with its cited lines, and under them the function's early exits above the last cited line: each `return`, `throw`, `continue`, `break` or `exit` that skips the cited code (a `continue` or `break` counts when its loop overlaps the cited lines). An exit marked `[inside the cited lines]` is one of the lines you cite: the sentence states its condition, or you narrow the cited range and the sentence to the lines before it. "No early exits" means none were found; "not listed" means the script could not read the file, so read the function yourself.

Go through the sentences twice in this session, before you hand the section over. A pass by any other session is a checker, not your audit.

- **First pass, in order.** Re-open each sentence's cited lines in the sheet, and the code around them when the sentence says what the code does. Compare each with the exits the sheet lists.
- **Second pass, the harsher read.** For each sentence, open the whole function it describes, not the lines you cite, and `grep` the repo for its callers. List what the sentence does not say: its other branches, its flags, its other callers, an ignore, allow or deny list, a value the function treats differently. Then narrow the sentence to the case it covers (rule 10) or cut it. When you find a condition for one function, search the draft for every other sentence that names that function, and fix them too.

Only then write the row for each sentence. One row per sentence, as many rows as sentences, never a summary ("1, 4-6 HOLDS"), and N is the doc line the sheet prints (`== doc line N`):

`N | assert: path:line "<the compared expression, copied from that line>" | exits: <each exit the sheet lists, as "path:line stated" or "path:line off the path: why", or "none listed"> | callers: <the other callers, flags, branches and lists the second pass found, each stated in the sentence or off its path, or "none found"> | found: <what the questions below turned up, or "nothing"> | result: HOLDS / narrowed to "..." / cut`

The assert must be one of the sentence's own citations, and its text must read as it does on that line. A line that repeats the one above with a few words changed, or that names no assert, has not been audited. For a sentence that says what a function does, every exit above the cited code must be stated in the sentence or be off its path; an exit you cannot place means you narrow the sentence to the test's case.

The questions, as a fresh checker asks them (`references/check-brief.md`). Be the harsher reader:

- A. An overreach word, count or full list, or "cannot", "is refused", "falls back"? Did you open the whole defining code?
- B. A condition, flag or branch the code has and the sentence lacks?
- C. A value or input that is only the test's own, said as the rule?
- D. Do the cited lines hold the asserting expression, and does it compare everything the sentence says? Read the expression, not the message.
- E. Who acted, the product or the scripted side?
- F. A comment, title or README that needs a label? A negative claim you did not grep?
- G. What a thing is, read from its definition?

When any answer is "no" or "not sure", edit the sentence now: narrow it to what the lines show, add the missing condition, add the line that does show it, or cut it if no narrower true sentence exists. Audit the edited sentence again. Stop when every line says HOLDS. A sentence you edited, or that no-ai-slop reworded, is audited again. Run the check with `--audit work/audit.md` (and without `--sheet`) once more on the final draft: it FAILs a sentence that has no row with all five fields whose assert is one of its own citations, with its text on that line. The draft that passes is the one you hand over.

## Stage 4: the PRD and DESIGN paragraphs for your capabilities

After the audit, write two short pieces beside `draft.md` (not in `work/`), `prd.md` (who gets what from your capabilities, and why it matters; budget P words) and `design.md` (what the pieces are, what each owns and how they fit; budget D words). Each sentence restates a sentence of your audited section in that doc's terms, with that sentence's citations and conditions, and keeps its narrowing ("in the test", "unless ..."). You add no claim about code you did not audit: a PRD or DESIGN sentence you cannot trace to an audited sentence is cut, or labelled inferred. Audit each piece the same way (`work/prd.audit.md`, `work/design.audit.md`) and run the check on it with `--max-words` and `--audit`. If an exception you found while auditing applies to a function a PRD or DESIGN sentence names, the sentence states it too. Why this is yours: the writer who read the code is the one who knows its branches; a writer given the whole repo to summarise reads each function less and misses them.

## Briefing a section writer (the lead)

Start one fresh session per section; never one session for the whole repo. The brief's first line names the seat and model the caller's table gives writers. Give it:

- The section: doc type (PRD, DESIGN or SPEC), the heading, and the style that doc needs (see `SKILL.md`).
- Its scope: the points it covers (ids from `points.json`) and the files they and the code they run sit in. Name topic and files only; do not paste earlier text or checker findings.
- The paths: the repo (read only, at the commit), `points.json` and `left-out.txt`, this skill's folder, and the one folder the writer may write in (`draft.md`, `prd.md`, `design.md` and `work/`).
- The method: read this file, and `SKILL.md` for the citation form and the rules for every sentence.
- Its budgets in words: B for the section, P and D for its PRD and DESIGN pieces (Stage 4), from the docs' budgets. Each draft runs `check_citations.py --max-words <budget> --audit <its audit file>` and fails when it is over or when a sentence has no audit row.
- Limits: no subagents, no step 8, no `--points` on the check (a section has no header or counts), no security or privacy language, read only the repo's tests, journeys and code (not its docs), change nothing in the repo.
- The report to send back: path of `draft.md`, number of sentences, the word count, the `Voice:` line, and in at most five lines what it could not cover or cut.
