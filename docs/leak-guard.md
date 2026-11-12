# leak-guard

`cartwmic/dotfiles` is a public repository, and the work machine commits to it. `leak-guard` is a git hook, on the work machine only, that checks every commit and push for work details before the change leaves the machine. There is no personal counterpart (see [profiles.md](./profiles.md)).

It is one script, `dot_local/bin/executable_leak-guard` (installed as `~/.local/bin/leak-guard`), run by three git hooks in the chezmoi source dir:

- `pre-commit` checks `git diff --cached`. It cannot see the commit message, and a commit with no diff (`git commit --allow-empty`) has nothing for it to read, so:
- `commit-msg` checks the message with layer 1 only (git's own `#` comment lines are ignored). It is a separate hook because only it is given the message; layer 2 reads every pushed message at pre-push. The author and committer of a commit are checked at pre-push, which sees them.
- `pre-push` checks, in one pass, everything the push would make public that the remote's own tracking refs do not already have:

      git rev-list <pushed tips> --not --remotes=<remote> [<each remote sha present locally>] \
        | git diff-tree --stdin -r -p --cc --root --no-renames --no-textconv --no-ext-diff --pretty=raw

  A commit that any branch of that remote has, as last fetched, is excluded and never rechecked; a commit shared by two pushed refs is checked once; the hook never fetches. Every commit is shown even when it has no diff (`--always`), so an empty commit's message and identities are checked too. Layer 1 scans every raw header line (author, committer, `mergetag`), every message line, every path and every added line; a merge shows only the lines it introduces itself (a `--cc` prefix as wide as the parent count, so an octopus merge works). Annotated tag objects are peeled and scanned whole (tagger included); a ref that peels to a tree or a blob blocks, since nothing here can read it. Only the **remote** ref name is checked, because the local name never becomes public. Deleted refs are skipped (a push of only deletes makes no Claude call). A push to a URL is mapped back to the configured remote whose `url` or `pushurl` it is; with no match, or with no tracking refs for that remote, it blocks with "run `git fetch <remote>`, then push again" rather than scanning the whole history. A remote sha that is not present locally gives a notice (run `git fetch`) and the check goes on over everything the tracking refs lack. Stale or divergent tracking refs only make the check examine more, never less; a `pushurl` that differs from `url`, or a custom fetch refspec, can make the exclusion wrong (this repository sets neither).

Both look only at **added** lines and at the **names** of added, copied, modified and renamed files (a rename counts as a new name; an empty file has a name too). File, branch and tag names are also given to Claude as data. Every diff is taken with `--no-textconv` and `--no-ext-diff`, so no diff driver can hide content. Because each commit's own patch is read, a term added in one commit and removed in the next is still seen, and pre-push backstops commits made with `--no-verify`.

**Binary files.** Their names are checked like any other, but their content cannot be read, so a binary file that is added or changed blocks (after layer 1, naming the file) until you commit it with the override. Two layers, cheapest first:

1. **Terms.** `~/.config/leak-guard/terms` is one regex per line (`#` lines are comments), matched case-insensitively. A hit blocks and prints `file:line: term`.
2. **Claude.** `claude -p` with Haiku, no tools and no MCP servers, in an empty directory, gets `~/.config/leak-guard/context` (a few lines on the employer and what counts as a work detail) and the added lines, and must answer one JSON object, `{"leak": true|false, "findings": [{"file", "line", "text", "why"}]}`. `leak: true` blocks and prints the findings. An answer that is not that JSON is a block, and so is one that contradicts itself (`leak: false` with findings, or findings that are not a list) or whose result is not text. An unexpected error blocks too, with the error's type named.

It **fails closed**. It blocks, with one line naming the failing step, when the `claude` CLI is missing, you are not signed in, the network is down, the call times out (120 s), `claude` exits non-zero, the terms or context file is missing, a term is not a valid regex, or a pre-commit change is over 200 KB (nothing is truncated; commit smaller changes or override), or one line of a push is larger than a 180 KB chunk. A push that is larger than one chunk is split into chunks of about 180 KB, each its own Claude call, and every chunk must pass.

## Override and bypass

- `LEAK_GUARD_SKIP="<reason>" git commit ...` (or `git push ...`) skips both layers for that one command, so it has to be set on each command that needs it (a commit runs three hooks, and a push one; the variable reaches each of them). **Every skip is logged**, with its reason, in the log below.
- `git commit --no-verify` and `git push --no-verify` skip the hooks, as git always allows. That leaves no log line.

## Log

Every run appends one line to `~/.local/state/leak-guard/log.jsonl` (the file is mode 600 in a mode 700 directory): `{utc, mode, head, verdict (pass|block|skip), layer (1|2|override|none), duration_s, findings}`, plus `claude_s` and `cost_usd` when Claude was called and `reason` for a skip or a failing step. Neither the diff nor any term is ever logged, and a `reason` is a short fixed code or a count (never a path, a ref name or a word from Claude's answer); notices such as `remote_sha_unknown` are logged as codes in `notes`.

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

`run_onchange_after_46_install-leak-guard-hooks.sh.tmpl` is a chezmoi `run_onchange_` step: it runs when the rendered script changes, that is when the `leakGuard` data (or the script) changes, and not on every apply. To re-run it by hand (after fixing a hook, or removing a foreign one): `chezmoi execute-template < "$(chezmoi source-path)/run_onchange_after_46_install-leak-guard-hooks.sh.tmpl" | sh`. It writes `.git/hooks/pre-commit` and `.git/hooks/pre-push` into the chezmoi source dir (each runs `~/.local/bin/leak-guard`), and `~/.config/leak-guard/terms` and `context` at mode 600. A hook file that already exists and is not leak-guard's is left alone with a warning. If `core.hooksPath` is set (globally or in the repo) nothing is installed, and the script says loudly that the chezmoi source repo is **UNGUARDED**, why (git then ignores `.git/hooks`, and a shared path would guard every repository), and how to fix it. With no `leakGuard` data, or on another profile, it does nothing. The terms are never in this repository: they live only in the machine's own chezmoi data. Git worktrees of the chezmoi source share its hooks.

## Tests

`python3 -m unittest discover -s tests/leak-guard -v`: a fake `claude` on PATH, invented terms and context. Layer 1 hits (file, line, term; regexes; file names; removed lines ignored), Claude's verdicts (leak, clean, wrapped JSON, unparseable), the call's flags (no tools, no MCP, the model, what is sent), missing `claude`, not signed in, timeout, an oversized change, the override and its log, the pre-push ranges (new branch, existing branch, a message, several refs, a deleted ref), the real hooks blocking a commit and a push and `--no-verify`, and the installer (nothing without data or on another profile, mode 600, a foreign hook left alone, bad data).
