# public-text-check: no private detail in new public text

`public-text-check` reads text that is about to become public in a public repository (a pull request or issue title and description, a comment or review, the messages of the commits a squash merge will put on main) and refuses it when it carries a private detail. It names the class and the line of each hit. It never prints the text that matched, so the refusal can be pasted anywhere.

## Where it runs

| Door | What it checks | File |
|---|---|---|
| `pr-open` create | title, rendered description, messages of the branch's commits, before the push | `dot_local/bin/executable_pr-open` |
| `pr-open --edit` | title (when given) and the description about to be patched | same |
| `issue-open` (also `--dry-run`) | title and expanded description | `dot_local/bin/executable_issue-open` |
| `pr-body-check REPO PR` (the merge form) | the description, title and commit messages of the PR as it stands | `dot_local/bin/executable_pr-body-check` |
| Bash hook: `gh pr comment`, `gh issue comment`, `gh pr review` with a body | comment text must be checked earlier in the same `&&` list | `dot_local/share/agent-harness/hooks/bash_rules.py` (`public_comment_rule`) |

The gh wrapper (`scripts/gh-wrapper`) already reads every gh text path, but the agent pod does not install it, so the checks sit at the doors an agent passes here.

Not covered: the direct forms the hook still accepts for a pull request, `pr-body-check --body-file F [--title T] && gh pr create|edit ...`, `pr-body-check --title T && gh pr edit N --title T` and a `gh api` PATCH of a title (`pr-open` is the checked path, and it needs a body file, so a title-only rename has no checked path; the merge form reads the title afterwards); `gh api` comment posts, `gh issue edit` or `close --comment`, `gh pr merge --body/--subject`, bodies on stdin, and a `git commit` made after the last `pr-open` and before the merge form (the merge form reads the commits again). The old text in `main` is not rewritten.

## The classes

One table: `dot_local/share/agent-harness/public-text-classes.json`, installed at `~/.local/share/agent-harness/public-text-classes.json` (`PUBLIC_TEXT_CLASSES_FILE` names another). Key `classes`; each row has `name`, `pattern` and optionally `surfaces` (`title`, `body`, `commit`; none means all three). Every pattern is in the subset that JavaScript (flags `iu`) and Python share, runs on one line at a time, and a test compiles each one in node. A comment is read with the rules of a body. The classes go beyond a plain list of paths: `runner log line` (a `kgate` log line in a body) is there because such lines carry pod names, and they are not meant to be public.

What a class lets pass on purpose: a placeholder user name in a home path (alice, bob, you, user, username, example, me, name); in the email class `git@`, an `@address` placeholder, `@example.`, `@users.noreply.github.com` and `@anthropic.com` (the attribution lines); in the runner-log class `user@address`.

Terms that are themselves private (the owner's name, a private repository's name, a host prefix) are not in the repository. They are lines in `~/.config/public-text-check/terms` (`PUBLIC_TEXT_TERMS_FILE` names another): one literal term per line, case-insensitive, `#` for comments, optionally `CLASS NAME<TAB>TERM`. When that file is missing the check says so in one line on stderr (names cannot be checked here) and the shape patterns still run.

## Scope

A private repository is not checked. A public one is, and so is one whose visibility cannot be read (`gh api` fails): it fails closed. `public-text-check --repo R --visibility` prints `private`, `public` or `unknown`; the hook asks it.

## A false hit

`PUBLIC_TEXT_SKIP="reason" public-text-check ...` passes a refusal, only when there were hits, and the record says `skipped` with the reason. The record never holds the text.

## Measure

Every run appends a line to `${XDG_STATE_HOME:-~/.local/state}/public-text-check/log.jsonl`: `utc, caller, repo, outcome (pass|refused|skipped|not-checked|failed), exit, surfaces, classes (hit counts), local_terms, skip_reason, duration_s`. The count of `skipped` lines is the count of false hits passed. If skips pass 1 in 5 of the refusals, the table has a bad class: fix its pattern.

To see the false-hit rate on a sample of recent merged descriptions: `scripts/public-text-sample.py OWNER/REPO [N]` runs the check over the N (default 50) merged pull requests that `gh pr list --state merged --limit N` returns, and prints, for each refused one, the class and line of each hit. A person then reads the refused ones: a real private detail is a catch, anything else is a false hit.

## Way back

Revert the commit that added it. The doors refuse when the command is not on PATH, so the revert removes the calls and the command in one step; the table and the hook rule go with it.

Exit status: 0 pass, not checked or skipped; 1 refused; 2 could not check (bad table, terms or gh failure): nothing passes then.
