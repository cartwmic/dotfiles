# The gh wrapper

One `gh` wrapper, first on PATH on every desktop profile. It is the leak-guard wrapper ([leak-guard.md](./leak-guard.md)) under a new name, with a seam for layers that save GitHub API calls. Every agent shares one GitHub account, and its core (REST) bucket of 5,000 calls an hour hit 0 twice on 2026-11-16. `gh run watch` alone costs about 4 REST calls per poll (run, jobs, workflow, annotations): 55 calls in 60 seconds at its default 3-second interval.

This page is the contract of the base. The layers themselves (log, watch interval and `gh api` cache, budget guard) are separate changes that add files to the lib directory, and each documents itself here when it lands.

## Where it lives

| What | Source in the dotfiles repo | Installed |
|---|---|---|
| the wrapper | `scripts/gh-wrapper` | `~/.local/share/gh-wrapper/bin/gh` (mode 755) |
| the lib: classification and the layer seam, later the layers | `scripts/gh-wrapper-lib/*.py` | `~/.local/share/gh-wrapper/lib/` |
| on/off switch for the layers | chezmoi data `ghBudget.enabled` | `~/.config/gh-wrapper/budget`, one word: `on` or `off` |
| PATH for mise shells | | `~/.config/mise/conf.d/gh-wrapper.toml` (`_.path`) |

`run_onchange_after_47_install-gh-wrapper.sh.tmpl` installs them: the lib first, then the budget file, then the wrapper, each by temp file and rename. It ships every `*.py` in `scripts/gh-wrapper-lib` and removes installed lib files the source no longer has, so adding a layer is adding a file, with no installer change. It renders on `personal` and `axon-work-computer`, not on Termux (out of scope in [profiles.md](./profiles.md)). A `gh` already at the wrapper path or a mise file already at its path that does not carry the mark `gh wrapper (managed by chezmoi` is left alone with a warning. Once the new wrapper is in place, the old install is removed when it carries the old mark: `~/.local/share/leak-guard/bin/gh` and `~/.config/mise/conf.d/leak-guard-gh.toml`.

To re-run it by hand: `chezmoi execute-template < "$(chezmoi source-path)/run_onchange_after_47_install-gh-wrapper.sh.tmpl" | sh`. To undo: delete `~/.local/share/gh-wrapper` and `~/.config/mise/conf.d/gh-wrapper.toml`.

## Getting first on PATH

`~/.local/share/gh-wrapper/bin` must come before every other `gh`. Three pieces do it, as they did for leak-guard: the mise file (mise puts `_.path` entries ahead of the real gh, and is the load-bearing one wherever mise is active), `dot_zshenv` (plain `zsh -c`) and `dot_zprofile` (login shells, after `/etc/zprofile`'s `path_helper`). `tests/leak-guard/test_gh_path.py` runs fresh `zsh -c`, `-lc`, `-ic` and `-lic` on a work install and on a personal install with no data, and checks each prints the wrapper. One host thing breaks it: a `gh` in `~/.local/share/mise/command-wrappers/bin`, which mise puts ahead of `_.path` (the Omarchy-owned directory). Remove a `gh` file there.

Service unit PATHs (t3code, coordinatord) are separate changes.

## What a call goes through

1. **Exempt:** `gh auth ...` and `gh --version` go straight to the real gh. Git's credential helper runs `gh auth git-credential` on every push and fetch (78 of 186 logged calls), and it makes no API call. Every exempt group is also in leak-guard's `NOT_REPO`, so skipping the check changes nothing (a test keeps it that way).
2. **Layers off** (`~/.config/gh-wrapper/budget` missing, or anything but `on`): straight to the leak-guard check below. Nothing in the lib directory is read. This is the work Mac.
3. **Layers on:** the command is classified, then each layer's `before` hook runs, then the leak-guard check, then the real gh, then each layer's `after` hook.
4. **Leak-guard check:** exactly as [leak-guard.md](./leak-guard.md) says, and only where `~/.config/leak-guard/repos` exists. It fails closed as before.
5. **Real gh:** found on PATH skipping any file with the mark, so the wrapper never finds itself. With no `after` hook anywhere, the wrapper replaces itself with gh (`exec`), as before. With one, it runs gh as a child and returns its exit code, standard input and output unchanged. While the child runs, SIGTERM and SIGHUP sent to the wrapper are passed on to gh (a timeout that kills only the process it started would otherwise leave a `gh run watch` polling), and the `after` hooks then see exit code 128 plus the signal. SIGINT from a terminal reaches gh directly.

## Classification (`gh_classify.py`)

Pure functions: the wrapper parses the command line and hands the facts in. A call has a `class`, a `bucket` and a `write` flag.

| Command | Bucket |
|---|---|
| `pr view`, `pr list`, `pr checks`, `pr status`, any `issue` command, `api graphql` | `graphql` |
| `api rate_limit` | `free` (costs nothing) |
| `search ...`, `api search/...` | `search` |
| everything else: `run *`, `workflow *`, `api <path>`, `pr diff`, and any command not named above | `core` |

`pr diff` spends one GraphQL and one REST call. It is recorded as `core`, the bucket that ran out. The table names only commands whose calls were measured with `GH_DEBUG=api`; the rest default to `core` until someone measures them.

**Read or write.** A call is a read only when it is a listed read command (leak-guard's `READ` table, plus `search`), or a `gh api` GET/HEAD (a method given with `-X`, else POST when any field or `--input` is given), or a GraphQL query known not to be a mutation. Everything else is a write: merge, create, comment, `workflow run`, non-GET `api`, a mutation, and any command or `gh api` call the wrapper could not read, including a GraphQL query that comes from a file or `--input`. A later layer that refuses reads therefore never refuses a call it cannot tell.

**Class.** `<group> <verb>` for a built-in command (`pr view`), the bare group for the groups leak-guard lists without verbs (`search`), `unrecognised` for an alias, an extension or a flag before the group, and `api <METHOD> <path>` for `gh api` with ids and shas in the path as `*` (`api GET repos/o/r/commits/*`) and `api POST graphql`. Never arguments, bodies or tokens.

## The layer seam (`gh_layers.py`)

A layer is a module in the lib directory. `LAYERS = ("gh_rewrite", "gh_budget", "gh_log")` fixes the order, and a name with no file is skipped. A layer may define:

- `before(call)`: change `call.args`, set `call.action` (`pass`, `rewrite`, `refused`, `exempt`) and `call.rewrite`, or `raise Stop(rc, message)` to refuse the call: the message goes to standard error, the wrapper exits `rc`, gh does not run.
- `after(call)`: runs once, in reverse order, whatever happened: gh's exit, a `Stop`, or a leak-guard block. `call.rc` is set.

`call` carries `args`, `klass`, `bucket`, `write`, `id` (the wrapper's pid), `t0`, `action`, `rewrite`, `rc` and a `notes` dict.

Invariant: **the layers never stop a call by failing.** If the lib cannot be loaded or the classification raises, the wrapper prints `gh-wrapper: the layers could not start (...); the call goes on without them` and runs the call with the leak-guard check only. **A layer's own exception never changes the call either.** It is reported on standard error as `gh-wrapper: layer <name> failed (...); the call goes on`, and the call goes on. Only a `Stop` changes it. A layer that cannot be imported is treated the same way, except one that simply is not there.

## The budget file

`~/.config/gh-wrapper/budget` holds `on` or `off`, written by the installer from the chezmoi data key `ghBudget.enabled` (`true` or `false`). Default: `on` on `personal`, `off` on `axon-work-computer`. A host with no file runs as off. The layers (log, watch interval and cache, budget guard) are all held by this one file.

## Profiles

| Profile | Gets |
|---|---|
| personal Linux | the wrapper, mise and shell PATH, the budget file `on` |
| personal Mac | the same; PATH through mise and `.zshenv` |
| work Mac | the same wrapper at the new path, leak-guard checks unchanged, the budget file `off`. A per-call log of directory and parent process, and refusing reads, are new on an employer machine, so Michael is asked before they are turned on there. |

## Tests

`python3 -m unittest discover -s tests/leak-guard`: `test_gh_layers.py` drives the classification, the exempt set and the seam through the installed layout (`bin/gh` next to `lib/`) with a fake real gh and fake layer modules; `test_gh_installer.py` runs the real template; `test_gh_path.py` the shells; `test_gh_wrapper.py` the leak-guard checks, unchanged.
