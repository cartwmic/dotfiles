# Helpers

If the harness can start subagents, use them to work in parallel. Pick each
helper's model from the house seat table:

| Seat | Model | Use it for |
| --- | --- | --- |
| Builder | Haiku 5.5 xhigh, or Sonnet 5.5 high on failure or when the work is ambiguous | Reading code, finding harnesses, summarizing logs |
| Planner | Sonnet 5.5 high | Proposing next ideas from the profile and the log |
| Reviewer | Opus 5.5 medium | The blocker review and the final review |

No OpenAI models.

- **Only you write in the climb tree.** `try` resets it, so a helper that
  edits it loses its work. A helper may read, or draft a fix in its own
  worktree and return a patch. You apply the patch and run `try`.
- **Run them in the background** while a check runs or setup installs. Don't
  wait on a helper when you have other work.
- **Brief them tight:** the goal, the files, and the answer shape, like
  "up to 5 ideas, each with file:line and an expected gain, under 200 words".
  Ask for conclusions, not file dumps.
- **Use as many as help.** Start one per independent question, all at once.
  Use the cheapest seat that can answer it. Don't start a helper for
  something two of your own tool calls can do.
- No subagents in this harness: do the same work inline.

Good moments for helpers:

- **Setup:** builder helpers map the code path, the tests, and any harness
  while you start the install.
- **Each long check:** planner helpers read the log, `notes.md`, and the profile,
  each from a different angle, and return the next ideas ranked by expected
  gain.
- **PLATEAU:** reviewer helpers do the blocker review with a fresh view.
- **Before the report:** reviewer helpers review the whole branch diff, for
  example one for correctness and one for what the change could break (see
  "Keep everything working").
