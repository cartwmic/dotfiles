Seat: reviewer (the model your seat table gives reviewers). You did not write this doc.
Check brief, version 6. Frozen for a lab and a climb: change it only with a log entry, because scores from different versions do not compare.

Check one slice of a derived doc against the repo. Inputs: the doc path, your line range of it, the repo path (at the commit in the doc header), and the flag list from `check_citations.py` for your range (`slice.py` cuts slices and builds the lists). Your slice is about 100 claims or fewer. The doc is one `GUIDE.md`: a plain-English Part 1, then an appendix whose sentences each carry `path:line` citations. Tests may or may not exist.

A claim is every sentence, bullet and table row in your range. Skip headings and anything between `<!-- printed -->` and `<!-- /printed -->` (a script printed those rows from the repo; they are not claims). For each one, open the cited lines yourself, and the code around them when the sentence says what the code does. Give each claim one verdict:

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

Part 1 sentences have no `path:line`. Each ends with tags such as `[A4.3f9a]` that point at appendix lines by id (an id stays with its line when the line is edited). Judge a Part 1 sentence against the tagged appendix sentences and the code they cite: it must say no more than they show, and it adds no number, name, quantifier or condition of its own. A tag that points at no appendix sentence, or at one about something else, makes it UNSUPPORTED. A Part 1 sentence may say "by default" or "in the default setup" only when a tagged line, or the code it cites, shows a default; if it shows none, the sentence is OVERSTATED. A Part 1 sentence may leave detail out; leaving out is not an error. A sentence that is misleading because of what it leaves out is OVERSTATED.

Checks every claim of these kinds must pass. Do them in addition to reading the cited lines:

1. Count, full set, next, every, always ("five words", "the next three wakes"): open the whole defining code (the full function, command or list), not the cited lines. Is the count the real count, the set the whole set? Did a cited test skip members, wakes or cases?
2. A behaviour stated flat ("cannot", "is refused", "falls back", "stays", "whatever X") or as "when X, Y": read the whole function for flags, branches, early exits, other callers and other values that behave differently (a flag, a type of input, target equal to current, no row against a different row). A condition the sentence lacks makes it OVERSTATED. A value that is only the test's own fixture, stated as the general rule, is OVERSTATED.
3. A negative claim ("no", "never", "does not", "cannot"): before you accept it, search the code yourself. Grep for the function, command, flag and message names and for a few words of the message. If the code does it, the claim is WRONG; name the file and line. A sentence about what tests cover ("no test covers X") is not allowed: the doc prints the test facts; mark it OTHER.
4. Only when a claim cites a test or journey: what it proves is its expect and assert lines and the values compared, not its setup, title or the code it starts. Read those lines. The claim must say no more than they compare (a rebuilt command that ran is not "the saved command ran"; a key and a part count are not "where it was posted"; a `node -e` child is not "a daemon"). Check that the behaviour sits under the trigger the test uses (a rule on plain `open` is not a rule of Review asks).
5. A claim that rests on a comment: the sentence must say so (for example "(code comment)"), the comment must say it, and the code must agree. If the code contradicts the comment (an "imports no component" comment on a file that imports two), the claim is WRONG; the fix is to drop it.
6. A claim about what a thing is or does by kind (a key, file, value, event, row, port): open its definition and its users, and name it by what they show. A name that sounds like one kind and is another is WRONG.
7. A claim that rests on a README or a doc must say so in the sentence. Without that it is OVERSTATED. If it does say so, check that the README really says it.

Report one line per non-HOLDS claim: `doc line | verdict | CAUSE | the words that fail | what the code shows (path:line) | the fix`. CAUSE is exactly one of these five words, the main reason the sentence fails, because a script counts them:

- MISSING_CONDITION: the code has a branch, flag, early exit, other caller or other case that the sentence does not state.
- NAME: a name, string, value or place that is wrong, invented or not in the cited lines.
- COUNT: a number, a count, a full list, or an overreach word (every, all, always, never, only, no X) that the code does not define.
- KIND: what a thing is, or who acted, is wrong: a key said to be a file, a scripted step said to be the product.
- OTHER: anything else, including a true claim with no citation.

End with one line, in this exact form: `Counts: claims checked N; HOLDS N; WRONG N; OVERSTATED N; UNSUPPORTED N.` The four verdict numbers add up to N, and there is one finding line for each WRONG, OVERSTATED and UNSUPPORTED. A script reads it. The lead names the file of a Part 1 slice `part1.md` or `part1-<anything>.md`; the script scores those apart from the appendix.
8. A default, limit or configuration value ("defaults to 30 seconds", "reads `server.yml`"): the sentence must cite the line that sets it, and the value must be on that line. A value taken from a README or help text must say so.

A value set on the cited line holds for COUNT: when the sentence names a number or name and the cited line sets it (a constant, a default, a limit), the line is the whole definition and the claim is not a COUNT error. COUNT is for a number or an overreach word that the code does not define.
