# Helpers

If the harness can start subagents, use them to work in parallel. Pick each
helper's model by the job, from the models the harness offers. Don't
hard-code a name:

| Tier | Example | Use it for |
| --- | --- | --- |
| Fast | the cheapest model, like a Haiku or mini class | Reading code, finding harnesses, summarizing logs |
| Mid | a Sonnet class model | Proposing next ideas from the profile and the log |
| Frontier | the strongest model, like an Opus class | The blocker review and the final review |

- **Only you write in the climb tree.** `try` resets it, so a helper that
  edits it loses its work. A helper may read, or draft a fix in its own
  worktree and return a patch. You apply the patch and run `try`.
- **Run them in the background** while a check runs or setup installs. Don't
  wait on a helper when you have other work.
- **Brief them tight:** the goal, the files, and the answer shape, like
  "up to 5 ideas, each with file:line and an expected gain, under 200 words".
  Ask for conclusions, not file dumps.
- **Use as many as help.** Start one per independent question, all at once.
  Use the cheapest tier that can answer it. Don't start a helper for
  something two of your own tool calls can do.
- No subagents in this harness: do the same work inline.

Good moments for helpers:

- **Setup:** fast explorers map the code path, the tests, and any harness
  while you start the install.
- **Each long check:** mid helpers read the log, `notes.md`, and the profile,
  each from a different angle, and return the next ideas ranked by expected
  gain.
- **PLATEAU:** frontier helpers do the blocker review with a fresh view.
- **Before the report:** frontier helpers review the whole branch diff, for
  example one for correctness and one for what the change could break (see
  "Keep everything working").
