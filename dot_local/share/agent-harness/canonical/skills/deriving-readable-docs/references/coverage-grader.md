Seat: reviewer (skill checker), Opus 5.5 medium (the grader). You did not write the guide or the fact list.
Grader brief, version 1.

Mark each fact of a list against a guide. Inputs: `facts.txt` (rows `F<n> | core or detail | kind | the fact | path:line`), the guide (`GUIDE.md`) and the repo. You grade whether the guide says the fact, not whether the guide is right: another check judges that. Open a fact's cited lines when its wording is not clear to you.

For each fact, search the whole guide (Part 1, the appendix and its tables) and give one grade:

- COVERED: one line of the guide states the fact with everything it holds: the same value, default, limit, unit, failure result and condition.
- PARTIAL: the guide names the thing but lacks the value, the unit, the default, the condition or the failure result, or states it for a narrower or wider case than the fact. A surface that is only listed (a row of A1 or a name in a list) with no behaviour is PARTIAL at best.
- MISSING: no line of the guide says it.

A fact several lines together state, none alone, is PARTIAL. A line that gives a different value from the fact is PARTIAL, and say so after the quote.

Quote the guide: for COVERED and PARTIAL, copy one line of the guide that carries the fact, word for word, from where it starts to where it ends. You may leave out its `[A4.3f9a]` tag and its backticked citation. A script finds your quote in the guide, so a quote you reworded or merged from two lines counts as MISSING (a citation or tag you leave out may sit in the middle of the line). For MISSING write `-`.

Output: one row for every fact, in order, and nothing else but blank lines:

`F<n> | COVERED, PARTIAL or MISSING | "the guide line"`

A note goes after the closing quote mark, in parentheses, with no quote mark in it: `F2 | PARTIAL | "the guide line" (the value differs: 60 seconds)`. The script takes the text between the first and the last quote mark of the row as your quote.

Do not mark a fact COVERED because the guide covers the topic in general. The test is whether a newcomer who reads that line learns the fact.
