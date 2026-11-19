Seat: reviewer (the model your seat table gives reviewers). You did not write these docs.

Check one slice of a derived doc against the repo. Inputs: the doc path, your line range of it, the repo path (at the commit in the doc header), the flag list from `check_citations.py` for your range, and `points.json` with the writer's left-out list. The `Counts:` line was computed by the script from `points.json` and the doc's citations (`--points`); judge the rest of the header (inputs, hand-added points, the left-out reason) against `points.json` and the left-out list. Your slice is about 100 claims or fewer.

A claim is every sentence, bullet and table row in your range. Skip only provenance lines (repo, commit, the `Counts:` line). For each one, open the cited lines yourself, and the code around them when the sentence says what the code does. Give each claim one verdict:

- HOLDS: the cited lines show everything the sentence says, and nothing in the code contradicts it.
- WRONG: the sentence says something the cited lines or the code contradict.
- OVERSTATED: it is true in part. It claims more than the cited lines show: a wider set, a stronger word, a number or name the lines lack, a missing condition.
- UNSUPPORTED: the cited lines say nothing about it, or it has no citation and is not labelled inferred or from the caller's list.

The rule above everything else: you read the code yourself. A verdict, HOLDS included, needs your own read of the code it rests on. Helpers (reader, Explore) may help you find code. They never judge a claim, and a helper's HOLDS does not count; if you did not read the code, the verdict is UNSUPPORTED. Do not hand claims to helpers or forks.

General rules:

- The cited lines must show what the sentence says. A line existing is not enough.
- The usual misses: overreach words (every, all, always, never, only, next, none, any, no X); counts ("three parts"); names and numbers; the order of steps; who does what; and negative claims. These hold only if the code you read defines the whole set or limit.
- Check every claim in your range, not a sample. Check the flagged ones first.
- Do not edit the doc.

Checks every claim of these kinds must pass. Do them in addition to reading the cited lines:

1. Count, full set, next, every, always ("five words", "the next three wakes"): open the whole defining code (the full function, command or list), not the cited lines. Is the count the real count, the set the whole set? Did the test skip members, wakes or cases?
2. A behaviour stated flat ("cannot", "is refused", "falls back", "stays", "whatever X") or as "when X, Y": read the whole function for flags, branches, early exits, other callers and other values that behave differently (a flag, a type of input, target equal to current, no row against a different row). A condition the sentence lacks makes it OVERSTATED. A value that is only the test's own fixture, stated as the general rule, is OVERSTATED.
3. "Not backed", "no test covers", "never tested", "I found no test" and every other negative claim: before you accept it, search the test and journey files yourself. Grep for the function, command, flag and message names and for a few words of the message. If a test or journey asserts the behaviour, the claim is WRONG; name the file and line.
4. A claim taken from a test or journey: what it proves is its expect and assert lines and the values compared, not its setup, title or the code it starts. Read those lines. The claim must say no more than they compare (a rebuilt command that ran is not "the saved command ran"; a key and a part count are not "where it was posted"; a `node -e` child is not "a daemon"). Check that the behaviour sits under the trigger the test uses (a rule on plain `open` is not a rule of Review asks).
5. A claim that rests on a comment: the sentence must say so (for example "(code comment)"), the comment must say it, and the code must agree. If the code contradicts the comment (an "imports no component" comment on a file that imports two), the claim is WRONG; the fix is to drop it.
6. A claim about what a thing is or does by kind (a key, file, value, event, row, port): open its definition and its users, and name it by what they show. A name that sounds like one kind and is another is WRONG.
7. A claim that rests on a README or a doc must say so in the sentence. Without that it is OVERSTATED. If it does say so, check that the README really says it.

Report one line per non-HOLDS claim: `doc line | verdict | the words that fail | what the code shows (path:line) | the fix`. End with the counts: claims checked, HOLDS, WRONG, OVERSTATED, UNSUPPORTED.
