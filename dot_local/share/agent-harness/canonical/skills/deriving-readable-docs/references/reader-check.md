# Reader check: can someone learn the product from Part 1 alone

Two fresh sessions, one script. The reader sees Part 1 only, never the repo. The grader sees the reader's answers and the repo, never the reader's reasoning. Why two: the script catches a quote the reader made up; only a grader reading the code can say an answer is wrong.

## Reader

Start a fresh Opus session with the output of `python3 -I <skill dir>/scripts/score.py --reader GUIDE.md`: the instructions, the five questions below and Part 1 with its tags removed. Nothing else: no repo, no appendix, no tools that read the web or the disk. It writes `answers.md`.

## Questions

1. In one sentence, what is it, and who would use it?
2. What are the main things a person can do with it? Name up to five.
3. What is the first thing someone does to start using it?
4. What does it need installed, read, or configured, and what does it write or keep?
5. Name one thing it does not do, or one case where it stops or says no.

The reader also lists every word or phrase it did not understand, under `## Unknown words`, one a line. Do not list a word the text defines where it first uses it. The list is printed in the report. It does not gate the pass. The guide may have a `## Glossary` at the end of Part 1 (`term: definition`, no length cap, optional); an entry for an outside term may carry no tag if it says nothing about the repo.

## Quote check (script)

`python3 -I <skill dir>/scripts/score.py --reader GUIDE.md --answers answers.md` exits 1 when a quoted sentence is not in Part 1, or when an answer has neither a quote nor the words NOT IN TEXT. It prints `unknown words: N (...)` from the reader's list and never fails for it. Fix the answers file only by asking the reader again; do not edit it.

## Grader

A fresh Opus session gets `answers.md` and the repo (at the commit), not the reader's reasoning. For each of the five answers it reads the code and marks CORRECT, PARTIAL, WRONG or NOT IN TEXT. NOT IN TEXT means Part 1 does not say it: that is a readability failure, not a wrong claim. It reports one line per answer: `Q1 | CORRECT | why, with a path:line`.

## Pass bar

5 of 5 CORRECT, no WRONG, every quote found, and `python3 -I <skill dir>/scripts/lint_main.py GUIDE.md <repo> --surfaces surfaces.json` passes. The unknown-word list does not gate. When the README and the code state no limit, Q5 may be NOT IN TEXT, and the bar is then 4 of 4 CORRECT among Q1 to Q4.

## One fix round

If the bar is missed, a fresh Opus front-writer session fixes Part 1 once (adds the missing answer or defines a word), without rewording a sentence in `fixed-ids.txt` (`lint_main.py --fixed fixed-ids.txt` warns when it does). The guide is checked again (`lint_main.py`, then the changed sentences by a fresh checker through `slice.py --ids`), and a fresh reader and grader run once more. Then report the result, pass or fail. There is no second fix round.

## Limit

The reader may know a well-known tool from its training. The quote rule and the grader catch a wrong answer; they cannot prove the reader learned it from Part 1. A repo no model was trained on (Michael's own) is the cleanest test.
