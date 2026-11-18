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
- A claim that rests on a README, a doc or a code comment must say so in the sentence, for example "(code comment)". Without that, it is OVERSTATED.
- Check every sentence in your range, not a sample. Check the flagged ones first.
- Do not edit the doc.

Report one line per non-HOLDS claim: `doc line | verdict | the words that fail | what the cited lines show (path:line) | the fix`. End with the counts: claims checked, HOLDS, WRONG, OVERSTATED, UNSUPPORTED.
