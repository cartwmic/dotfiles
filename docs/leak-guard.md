# leak-guard

`cartwmic/dotfiles` is a public repository, and the work machine commits to it. `leak-guard` is a git hook, on the work machine only, that checks every commit and push for work details before the change leaves the machine. There is no personal counterpart (see [profiles.md](./profiles.md)).

It is one script, `dot_local/bin/executable_leak-guard` (installed as `~/.local/bin/leak-guard`), run by two git hooks in the chezmoi source dir:

- `pre-commit` checks `git diff --cached`.
- `pre-push` checks, for each pushed ref, what the remote does not have: the remote's current commit up to the pushed one, or for a new ref the merge-base with the remote's default branch (`refs/remotes/<remote>/HEAD`, else `main` or `master`) up to the pushed one. With no such tracking ref the push is blocked with a reason (fetch the remote, or `git remote set-head <remote> -a`) rather than scanning from the first commit. A deleted ref is not checked.

Both look only at **added** lines and at the **names** of added, copied, modified and renamed files (a rename counts as a new name; an empty file has a name too). At pre-push they also check commit messages, the pushed branch and tag names, and annotated tag messages.

**Binary files.** Their names are checked like any other, but their content cannot be read, so a binary file that is added or changed blocks (after layer 1, naming the file) until you commit it with the override. Two layers, cheapest first:

1. **Terms.** `~/.config/leak-guard/terms` is one regex per line (`#` lines are comments), matched case-insensitively. A hit blocks and prints `file:line: term`.
2. **Claude.** `claude -p` with Haiku, no tools and no MCP servers, in an empty directory, gets `~/.config/leak-guard/context` (a few lines on the employer and what counts as a work detail) and the added lines, and must answer one JSON object, `{"leak": true|false, "findings": [{"file", "line", "text", "why"}]}`. `leak: true` blocks and prints the findings. An answer that is not that JSON is a block, and so is one that contradicts itself (`leak: false` with findings).

It **fails closed**. It blocks, with one line naming the failing step, when the `claude` CLI is missing, you are not signed in, the network is down, the call times out (120 s), `claude` exits non-zero, the terms or context file is missing, a term is not a valid regex, or the change is over 200 KB (nothing is truncated; commit smaller changes or override).

## Override and bypass

- `LEAK_GUARD_SKIP="<reason>" git commit ...` (or `git push ...`) skips both layers for that one command. The skip is logged with its reason.
- `git commit --no-verify` and `git push --no-verify` skip the hooks, as git always allows. That leaves no log line.

## Log

Every run appends one line to `~/.local/state/leak-guard/log.jsonl` (the file is mode 600 in a mode 700 directory): `{utc, mode, head, verdict (pass|block|skip), layer (1|2|override|none), duration_s, findings}`, plus `claude_s` and `cost_usd` when Claude was called and `reason` for a skip or a failing step. Neither the diff nor any term is ever logged.

## What it guards

Only the chezmoi source checkout, and the git worktrees made from it (they share its hooks directory). **A separate clone of the repository is not guarded**: hooks are not part of a clone, so a clone made elsewhere has none until you install them there by hand.

## Installing it

On the `axon-work-computer` profile, with the data key `leakGuard` in `~/.config/chezmoi/chezmoi.yaml`:

```yaml
data:
  leakGuard:
    terms: ["fooco", "project-bar"]       # regexes
    context: |
      Fooco is the employer. A work detail is anything that names it, its hosts, its repositories or its registries.
```

`run_onchange_after_46_install-leak-guard-hooks.sh.tmpl` then writes `.git/hooks/pre-commit` and `.git/hooks/pre-push` into the chezmoi source dir (each runs `~/.local/bin/leak-guard`), and `~/.config/leak-guard/terms` and `context` at mode 600. A hook file that already exists and is not leak-guard's is left alone with a warning. If `core.hooksPath` is set (globally or in the repo) nothing is installed and the script says why: a shared hooks path would guard every repository that uses it, not just this one. With no `leakGuard` data, or on another profile, it does nothing. The terms are never in this repository: they live only in the machine's own chezmoi data. Git worktrees of the chezmoi source share its hooks.

## Tests

`python3 -m unittest discover -s tests/leak-guard -v`: a fake `claude` on PATH, invented terms and context. Layer 1 hits (file, line, term; regexes; file names; removed lines ignored), Claude's verdicts (leak, clean, wrapped JSON, unparseable), the call's flags (no tools, no MCP, the model, what is sent), missing `claude`, not signed in, timeout, an oversized change, the override and its log, the pre-push ranges (new branch, existing branch, a message, several refs, a deleted ref), the real hooks blocking a commit and a push and `--no-verify`, and the installer (nothing without data or on another profile, mode 600, a foreign hook left alone, bad data).
