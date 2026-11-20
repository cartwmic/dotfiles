# Drafting a section: assert-first, then a written audit

For the section writer: a fresh session that drafts one section of the appendix (`A4` and on), or the frame (`A3`). The lead's brief (last part of this file) names the section, its capability, its files and your work folder. Why this method: in a lab on test-cited claims, one fresh writer per section using it had 4.6% (coordinator) and 3.7% (agent-kit) of claims wrong on the first pass, against about 16% for one whole-repo writer. Most errors left were a sentence true on one path of a function and false on another, so the audit uses the exits that `check_citations.py --sheet` lists. Whether the rate holds for claims cited to code, on repos with few tests, is not measured yet.

Why a budget: the first run of this method, with no limit, wrote 3,800 claims (88,000 words) for a repo whose earlier draft had 540, and the number of wrong claims went up from 88 to 189. About 6 in 10 of them dropped a condition the code has (a branch, a flag, another caller). You have a word budget: write fewer, better-read sentences.

Keep your work files in your work folder. They are not part of the draft and are never cited. Fresh checkers are not yours; the audit below is your own pass, so the checker finds nothing.

## What counts as evidence

In this order: **code** (entry points, command and flag registrations, route tables, config loaders and their defaults, public interfaces) defines what the product does; **the repo's own words** (README, `docs/`, help text, comments) give intent and names, and the sentence says so ("README", "help text", "code comment"); **tests** confirm a behaviour. A test cited alone supports only "in the test". A repo may have no tests: draft from code and the repo's own words, and cite the line that defines each behaviour. A rule you cannot read end to end (long, spread over files, generated) is not described as a behaviour; state the surface only: "`--foo` takes a number (help text)". Never write "no test covers X": the guide prints what tests cover.

## Stage 0: choose (`work/choice.md`)

Your budget is B words, counted as the check counts them: a word is any space-separated token with a letter, digit or underscore in it, and every such token of the draft counts, headings and backticked names included. Citations, fenced code, printed blocks and bare marks (`-`, `1.`, `##`) do not. A sentence is about 14 words (the lab's limit arm averaged 12.8), so you have about B/14 sentences. From the surfaces and code of your capability, list the behaviours a reader most needs, one line each, and keep the first B/14. Prefer a behaviour whose rule you can read end to end: the one function or command, its branches stated in one clause. Leave out a behaviour whose defining code has more branches than you can state. Do not reach the budget by joining two behaviours into one sentence or by generalising ("the command refuses bad input"): drop the behaviour.

## Stage 1: evidence file (`work/evidence.md`)

For each behaviour you kept, and only those, open the code that defines it, the whole function or command and its helpers, and write one row per line you will cite:

| row | `path:line` | the line, verbatim | trigger: who calls it, with which input | value or effect, verbatim | set here, or by the caller or a fixture? | the conditions of the whole function |

- **The line, verbatim**: copy the line. Do not copy a comment, a log message or a name that says more than the line does.
- **Trigger**: the entry point, flag, route or caller that reaches it. For a test row, say who ran it: the product code, or the test's own scaffolding (a scripted turn, a stub, a double, a hand-written fixture). A thing the scripted side does is not product behaviour. If a rerun differs from the first run in any argument, say so.
- **Set here**: yes only when the line defines the value (a default, a constant, a limit). A value that comes from a caller, a config file or a test's own choice is an example, not the rule.
- **Conditions**: open the whole function and write its flags, branches, early exits, skipped inputs, other callers and other values. `python3 -I <skill dir>/scripts/early_exits.py <file> <line>` lists the exits above a line of a function (Python and TS/JS). Write "not read" if you did not open it: a "not read" row backs only a sentence worded "in the test" or "(help text)".
- For a test or journey row: the compared expression and the value it is compared with, not the title or the failure message. If the line compares only a count, a length or the existence of a row, write that.

Then add one line per behaviour you plan to describe, naming the rows it rests on.

## Stage 2: draft

1. Each sentence restates one or more evidence rows, with their conditions, and says no more than those rows show. Write it from the rows, not from your memory of the code.
2. One behaviour per sentence, at most 18 words, counted as the check counts them (citations are not words). Name the case in the sentence: "when X, Y". When a behaviour needs more words, split it and keep the condition in each part: "When X, Y does A. When X, Y also does B."
3. A value from a caller, a fixture or a test goes in as an example ("in the test", "for example"), not as the rule.
4. Copy numbers, names, flags, messages and the place a result appears (standard output, the log, the exit code) from the cited line, not from memory or a summary.
5. A sentence that says a thing happens in the product needs a code row with its conditions, and states each one that applies: the flag, the input kind, the other caller, the case that returns earlier. What a key, file, value or event is comes from its definition and its users.
6. Say who did something only as the row's trigger shows.
7. Words that exist only in a failure message, test title, comment or README stay out, or carry the label "(test title)", "(code comment)" or "(README)" when the code agrees.
8. No "all", "every", "none", "only", "always", counts or full lists unless the code row defines the whole set.
9. Cite the line that shows what the sentence names: where a limit is checked, a default is set, a command is called, not the nearby loop, signature or comment. Cite directly after the sentence the code lines it rests on, as `SKILL.md` requires.
10. Narrow, do not stack. When a sentence would need a branch, flag, caller or exception it does not state, narrow the claim to the case you read or drop it. Do not add clause after clause ("unless A, B or C"): a sentence that needs two "unless" clauses is about the wrong case. Add an exception only when you have read it in the code and cite its line. Do not hedge ("usually", "may") and do not pad.
11. Write for a person. The sentences stay narrow, each with its own citation, but lay them out as short paragraphs or list items grouped by what the reader wants to know, not as one claim per line where that hurts reading. Do not merge two behaviours into one sentence to save space.

Then load `no-ai-slop` (Skill tool) and apply it in edit mode to the draft, keeping every citation, number and name as written. Put the `Voice:` line in your report. Run `python3 -I <skill dir>/scripts/check_citations.py draft.md <repo> --max-words B --max-sentence-words 18` and fix every FAIL, a sentence over 18 words included.

## Stage 3: audit (`work/audit.md`)

Run the same command with `--sheet`. It prints each sentence with its cited lines, and under them the function's early exits above the last cited line: each `return`, `throw`, `continue`, `break` or `exit` that skips the cited code (a `continue` or `break` counts when its loop overlaps the cited lines). An exit marked `[inside the cited lines]` is one of the lines you cite: the sentence states its condition, or you narrow the cited range and the sentence to the lines before it. "No early exits" means none were found; "not listed" means the script could not read the file, so read the function yourself.

Go through the sentences twice in this session, before you hand the section over. A pass by any other session is a checker, not your audit.

- **First pass, in order.** Re-open each sentence's cited lines in the sheet, and the code around them when the sentence says what the code does. Compare each with the exits the sheet lists.
- **Second pass, the harsher read.** For each sentence, open the whole function it describes, not the lines you cite, and `grep` the repo for its callers. List what the sentence does not say: its other branches, its flags, its other callers, an ignore, allow or deny list, a value the function treats differently. Then narrow the sentence to the case it covers (rule 10) or cut it. When you find a condition for one function, search the draft for every other sentence that names that function, and fix them too.

Only then write the row for each sentence. One row per sentence, as many rows as sentences, never a summary ("1, 4-6 HOLDS"), and N is the doc line the sheet prints (`== doc line N`):

`N | assert: path:line "<the line, copied from that line>" | exits: <each exit the sheet lists, as "path:line stated" or "path:line off the path: why", or "none listed"> | callers: <the other callers, flags, branches and lists the second pass found, each stated in the sentence or off its path, or "none found"> | found: <what the questions below turned up, or "nothing"> | result: HOLDS / narrowed to "..." / cut`

The assert must be one of the sentence's own citations, and its text must read as it does on that line. A line that repeats the one above with a few words changed, or that names no assert, has not been audited. For a sentence that says what a function does, every exit above the cited code must be stated in the sentence or be off its path; an exit you cannot place means you narrow the sentence to the case you read.

The questions, as a fresh checker asks them (`references/check-brief.md`). Be the harsher reader:

- A. An overreach word, count or full list, or "cannot", "is refused", "falls back"? Did you open the whole defining code?
- B. A condition, flag or branch the code has and the sentence lacks?
- C. A value or input that is only a caller's, a fixture's or a test's own, said as the rule?
- D. Do the cited lines hold the line that shows what the sentence says? Read the line, not the comment above it.
- E. Who acted, the product or a scripted side?
- F. A comment, title or README that needs a label? A negative claim you did not grep?
- G. What a thing is, read from its definition?

When any answer is "no" or "not sure", edit the sentence now: narrow it to what the lines show, add the missing condition, add the line that does show it, or cut it if no narrower true sentence exists. Audit the edited sentence again. Stop when every line says HOLDS. A sentence you edited, or that no-ai-slop reworded, is audited again. Run the check with `--audit work/audit.md` (and without `--sheet`) once more on the final draft: it FAILs a sentence that has no row with all five fields whose assert is one of its own citations, with its text on that line. The draft that passes is the one you hand over.

## Briefing the writers (the lead)

Start one fresh session per writer; never one session for the whole repo. Each brief's first line names the seat and model the caller's table gives writers. Common to all three:

- The paths: the repo (read only, at the commit), `surfaces.json` and `scout.txt`, this skill's folder, and the one folder the writer may write in (`draft.md` and `work/`).
- The method: read this file, and `SKILL.md` for the citation form and the rules for every sentence.
- Limits: no subagents, no security or privacy language, change nothing in the repo. Each draft runs `check_citations.py --max-words <budget> --max-sentence-words 18 --audit <its audit file>` and fails when it is over, when a sentence has more than 18 words, or when a sentence has no audit row.

**Section writer** (one per capability, `A4` and on). The section heading `## A<n> <capability>`; the capability and its surfaces by name; the files its code sits in (names only, no earlier text and no checker findings); its word budget B. Report: path of `draft.md`, number of sentences, the word count, the `Voice:` line, and in at most five lines what it could not cover or cut.

**Frame writer** (one, `A3`, heading `## A3 The product as a whole`). Writes, from the README (labelled), the directory layout, the entry points and manifests and the config loaders: purpose and users; the parts and what each owns, each with its `path:line`; what it needs and keeps; stated limits. It follows Stages 0 to 3 and its budget is the A3 budget.

**Front writer** (one, Part 1). Gets the assembled appendix and `assemble.py --index` output (every appendix sentence with its tag `A<n>.<k>`), and nothing else about the repo: it does not open the code. It writes Part 1 as plain English under five headings: what it is and who it is for; what you can do (up to eight capabilities, one short paragraph each); how the parts fit (at most six sentences); what it needs and keeps; what it does not do. Every sentence ends with the tags of the one to three appendix sentences it restates. It may drop detail. It adds no fact, no number, no quantifier and no condition the tagged sentences lack. No `path:line` and no more than three `--flag` tokens. Part 1 passes `lint_main.py` before it is handed over.
