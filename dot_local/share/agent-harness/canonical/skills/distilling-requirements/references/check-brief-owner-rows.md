Addendum to `check-brief.md` for a register slice (give the checker both). It changes nothing in the brief except how to judge the claims named here.

A row can hold more than one sentence, and the claim list has one claim for each sentence (`N.1`, `N.2`, ...). The tag `(owner requirement)` is on the last sentence only, so do not look for the tag. Every claim `N.k` whose `N` is a doc line in `owner-notes.txt` is part of one owner row, and all of its claims are judged with that row's note. The note is the line that starts with `N`: `N | R-id | note`. Read the note with each sentence of the row. The note is not a claim of its own: it has no row in your report.

A row whose evidence includes `owner:interview` states what the owner requires, not what the code does today. Judge whether the row's sentence and its note, read together, describe truly how far the cited code meets that requirement, including what it does not meet. A sentence that plainly states the owner's requirement and says the code does not meet it HOLDS if the cited code shows the gap.

Everything else in the brief holds: open the cited lines and the code around them yourself, give each claim one verdict, and report a `read` row for every claim. A sentence that says the code meets the requirement, or that is silent about a gap the note admits, is judged as the brief says.
