# Fix rounds (step 9 of SKILL.md)

Round 1 is the checkers' reports on the whole guide. Each later round re-checks only the sentences that changed. At most 2 fix rounds after round 1.

## Who fixes what

- Appendix findings: the lead edits the section files itself, then runs `stamp.py` on them. A line keeps its id, so the Part 1 tags that point at it hold.
- A fix that splits a sentence splits it. It does not paste the checker's wording: that breaks the 18-word limit.
- A Part 1 finding is fixed by a fresh Opus front-writer session. When the finding is a missing condition, Part 1 cannot state what its tagged appendix line lacks, so the lead also puts the condition on that appendix line, in the same round.
- After fix round 2 the lead makes every cut, a Part 1 sentence included. A sentence that still fails is cut, or narrowed to what the code shows.

## Part 1 over 1,000 words

`lint_main.py` fails Part 1 over 1,000 words at every step, fix rounds included. A fix that adds a condition grows a sentence: cut to fit in this order. First shorten or merge the sentences a fix narrowed (a merged sentence keeps every condition its tags state, and the 18-word limit). Then drop a What you can do line the appendix covers in full. Never cut How to start or the Who it is for sentence.

## The commands, in order

1. Rerun the step 8 script (`check_citations.py` with the budget flags) on the fixed guide. A fix can break a citation or the budget, and `slice.py` reads the guide as it stands.
2. List the changed ids in `changed.txt` and run `python3 -I <skill>/scripts/slice.py GUIDE.md <repo> --ids changed.txt --out slices-fixN --was <the guide as last cut>`. It cuts Part 1 and the appendix apart, each into slices of near-equal size. With `--was`, it also picks up a line a fix split, reworded or moved, found by comparing its text with the old guide as well as its id.
3. One fresh Opus checker per slice, with `references/check-brief.md`, reports into `reports-fixN`.
4. `python3 -I <skill>/scripts/slice.py GUIDE.md <repo> --ids changed.txt --reports reports-fixN --record-fixed fixed-ids.txt`. A Part 1 sentence whose re-check says HOLDS is recorded as it stands, and any other as `cut`. `lint_main.py --fixed fixed-ids.txt` then warns when a front writer rewords a recorded sentence, and skips a `cut` row.
5. Score the round's reports against that round's own slices folder: `score.py <name>=reports-fixN --doc GUIDE.md --repo <repo> --slices slices-fixN`. Its words and rates are those of the re-checked sentences.
