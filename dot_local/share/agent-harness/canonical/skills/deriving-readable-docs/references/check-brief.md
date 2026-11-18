Seat: reviewer (the model your seat table gives reviewers). You did not write these docs.

Check one slice of a derived doc against the repo. Inputs: the doc path, your line range of it, the repo path (at the commit in the doc header), and the flag list from `check_citations.py` for your range.

For every sentence, bullet and table row in your range, open the cited lines, and the code around them when the sentence says what the code does. Give each one verdict:

- HOLDS: the cited lines show everything the sentence says, and nothing in the code contradicts it.
- WRONG: the sentence says something the cited lines or the code contradict.
- OVERSTATED: it is true in part. It claims more than the cited lines show: a wider set, a stronger word, a number or name the lines lack.
- UNSUPPORTED: the cited lines say nothing about it, or it has no citation and is not labelled inferred or from the caller's list.

Rules:

- The cited lines must show what the sentence says. A line existing is not enough.
- The usual misses: overreach words (every, all, always, never, only, none, any, no X); counts ("three parts"); names and numbers; the order of steps; who does what; and negative claims ("never reads", "no test covers"). A claim like these holds only if a cited line defines the whole set or limit. Open the file when the sentence says "only" or "never"; one line seldom proves it.
- A claim of either kind below is not judged from the cited lines. Open the code that defines it, read it yourself in full (the whole function, command or list), and judge from that. A helper's or search's HOLDS is not enough; if you did not read the code, the verdict is UNSUPPORTED.
  - Count, full set, next, every, always ("five words", "the next three wakes"): a test proves only the cases it runs. Find the definition or the loop. Is the count the real count, the set the whole set? Did the test skip some wakes, items or cases?
  - A behaviour stated flat ("cannot", "is refused", "falls back", "stays", "whatever X"): look in the function for flags, branches and early exits that skip it, and for other callers or values that behave differently. If it has a condition the sentence lacks, it is OVERSTATED.
- A claim that rests on a README, a doc or a code comment must say so in the sentence, for example "(code comment)". Without that, it is OVERSTATED.
- Check every sentence in your range, not a sample. Check the flagged ones first.
- Do not edit the doc.

Report one line per non-HOLDS claim: `doc line | verdict | the words that fail | what the cited lines show (path:line) | the fix`. End with the counts: claims checked, HOLDS, WRONG, OVERSTATED, UNSUPPORTED.
