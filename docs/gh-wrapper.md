# The gh wrapper

One `gh` wrapper, first on PATH on every desktop profile and in container mode. It is the leak-guard wrapper ([leak-guard.md](./leak-guard.md)) under a new name, with a seam for layers that save GitHub API calls. Every agent shares one GitHub account, and its core (REST) bucket of 5,000 calls an hour hit 0 twice on 2026-11-16. `gh run watch` alone costs about 4 REST calls per poll (run, jobs, workflow, annotations): 64 calls in 60 seconds at its default 3-second interval (measured with `-i 3`).

This page is the contract of the base. The layers themselves (log, watch interval and `gh api` cache, budget guard) are separate changes that add files to the lib directory, and each documents itself here when it lands.

## Where it lives

| What | Source in the dotfiles repo | Installed |
|---|---|---|
| the wrapper | `scripts/gh-wrapper` | `~/.local/share/gh-wrapper/bin/gh` (mode 755) |
| the lib: classification and the layer seam, later the layers | `scripts/gh-wrapper-lib/*.py` | `~/.local/share/gh-wrapper/lib/` |
| on/off switch for the layers | chezmoi data `ghBudget.enabled` | `~/.config/gh-wrapper/budget`, one word: `on` or `off` (read by the wrapper, not the installer) |
| on/off switch for the work rules | the profile (`personal` on, anything else off) | `~/.config/gh-wrapper/policy`, one word: `on` or `off` (read by the `gh_policy` layer) |
| PATH for mise shells | | `~/.config/mise/conf.d/gh-wrapper.toml` (`_.path`) |

`run_onchange_after_47_install-gh-wrapper.sh.tmpl` installs them: the lib first, then the budget file, then the wrapper, each by temp file and rename. It ships every `*.py` in `scripts/gh-wrapper-lib` and removes installed lib files the source no longer has, so adding a layer is adding a file, with no installer change. It renders on `personal` and `axon-work-computer`, not on Termux (out of scope in [profiles.md](./profiles.md)), and container mode keeps it (its script is in the container's `$keep` list in `.chezmoiignore`; `tests/container-mode` fails without it). A `gh` already at the wrapper path or a mise file already at its path that does not carry the mark `gh wrapper (managed by chezmoi` is left alone with a warning. Once the new wrapper is in place, the old install is removed when it carries the old mark: `~/.local/share/leak-guard/bin/gh` and `~/.config/mise/conf.d/leak-guard-gh.toml`.

To re-run it by hand: `chezmoi execute-template < "$(chezmoi source-path)/run_onchange_after_47_install-gh-wrapper.sh.tmpl" | sh`. To undo: delete `~/.local/share/gh-wrapper` and `~/.config/mise/conf.d/gh-wrapper.toml`.

## Getting first on PATH

`~/.local/share/gh-wrapper/bin` must come before every other `gh`. Three pieces do it, as they did for leak-guard: the mise file (mise puts `_.path` entries ahead of the real gh, and is the load-bearing one wherever mise is active), `dot_zshenv` (plain `zsh -c`) and `dot_zprofile` (login shells, after `/etc/zprofile`'s `path_helper`). `tests/leak-guard/test_gh_path.py` runs fresh `zsh -c`, `-lc`, `-ic` and `-lic` on a work install and on a personal install with no data, and checks each prints the wrapper. One host thing breaks it: a `gh` in `~/.local/share/mise/command-wrappers/bin`, which mise puts ahead of `_.path` (the Omarchy-owned directory). Remove a `gh` file there.

Service unit PATHs (t3code, coordinatord) are separate changes. In container mode there is no systemd. The installer writes the link `~/.local/bin/gh` to the wrapper, and the pod image's `ENV PATH` starts with `~/.local/bin`, so the T3 server, its sessions and the coordinator daemon find the wrapper first ([container-mode.md](./container-mode.md)).

## What a call goes through

1. **Exempt:** `gh auth ...` and `gh --version` go straight to the real gh. Git's credential helper runs `gh auth git-credential` on every push and fetch (78 of 186 logged calls), and it makes no API call. Every exempt group is also in leak-guard's `NOT_REPO`, so skipping the check changes nothing (a test keeps it that way).
2. **Layers off** (`~/.config/gh-wrapper/budget` missing, or anything but `on`): only the layers in `ALWAYS` run (`gh_rewrite`, whose watch-interval default is on every profile, its `gh api` cache waiting for the budget file; and `gh_policy`, which reads its own switch, [the work rules](#the-work-rules-gh_policypy)). The budget and log layers are not read. This is the work Mac.
3. **Layers on:** the command is classified, then each layer's `before` hook runs, then the leak-guard check, then the real gh, then each layer's `after` hook.
4. **Leak-guard check:** exactly as [leak-guard.md](./leak-guard.md) says, and only where `~/.config/leak-guard/repos` exists. It fails closed as before.
5. **Real gh:** found on PATH skipping any file with the mark, so the wrapper never finds itself. With no `after` hook anywhere, the wrapper replaces itself with gh (`exec`), as before. With one, it runs gh as a child and returns its exit code, standard input and output unchanged. While the child runs, SIGTERM, SIGHUP and SIGINT sent to the wrapper are passed on to gh (a timeout that kills only the process it started would otherwise leave a `gh run watch` polling, and an interrupt sent only to the wrapper would leave gh running), and the `after` hooks then see exit code 128 plus the signal. A terminal's Ctrl-C reaches the wrapper and gh both, so gh gets the interrupt twice.

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

A layer is a module in the lib directory. `LAYERS = ("gh_policy", "gh_rewrite", "gh_budget", "gh_log")` fixes the order, and a name with no file is skipped. `ALWAYS = ("gh_policy", "gh_rewrite")` names the layers that also run when the budget file is off (`gh_policy` has its own switch, below). A layer may define:

- `before(call)`: change `call.args`, set `call.action` (`pass`, `rewrite`, `refused`, `exempt`) and `call.rewrite`, or `raise Stop(rc, message)` to refuse the call: the message goes to standard error, the wrapper exits `rc`, gh does not run.
- `after(call)`: runs once, in reverse order, whatever happened: gh's exit, a `Stop`, or a leak-guard block. `call.rc` is set.

`call` carries `args`, `klass`, `bucket`, `write`, `budget_on` (whether the budget file says `on`), `real` (the real gh, for a layer that reads state from GitHub), `parsed` (the flags of a `run watch`, `pr checks`, `pr create`, `pr merge`, `issue create`, `issue close` or `gh api` call as the wrapper read them: `([(long name, value or None)], [positional arguments])`, or `None` for another command or flags it could not read), `id` (the wrapper's pid), `t0`, `action`, `rewrite`, `rc` and a `notes` dict.

Invariant: **the layers never stop a call by failing.** If the lib cannot be loaded or the classification raises, the wrapper prints `gh-wrapper: the layers could not start (...); the call goes on without them` and runs the call with the leak-guard check only. **A layer's own exception never changes the call either.** It is reported on standard error as `gh-wrapper: layer <name> failed (...); the call goes on`, and the call goes on. Only a `Stop` changes it. A layer that cannot be imported is treated the same way, except one that simply is not there. With the budget file off or missing (the work Mac), a lib that is not installed at all is silent, as it was before the layers existed; a lib that is there and broken still prints the line.

## The budget guard (`gh_budget.py`)

A layer that refuses a read when its bucket is nearly empty, so that one agent's polling cannot leave the others with a 403. It acts only where the budget file says `on`.

| Call | What the guard does |
|---|---|
| a read on `core` or `graphql` | reads the bucket's `remaining`; under the floor (600) it refuses |
| a write (merge, `workflow run`, `run rerun`, `pr create/edit/comment`, non-GET `api`, a GraphQL mutation, and any call the wrapper could not read) | passes, no rate read |
| any call with `GH_URGENT=1` in its environment | passes, no rate read |
| `gh api rate_limit` (`free`) and `search` | never refused |
| a host other than github.com (`GH_HOST`, or `gh api --hostname`) | skipped |
| a cached low reading whose reset time has passed | passes (the reading is out of date) |
| the rate read fails, or takes over 3 seconds | passes (fail open) |

Each command is judged on its own bucket: `pr view` on `graphql`, `run list` on `core` (the table is [Classification](#classification-gh_classifypy)), so an empty core bucket does not stop `pr view`.

**Refusal.** Exit code 75, one line on standard error, no `gh` call, no waiting (a wait could hang an agent for up to an hour):

```
gh-wrapper: core budget low: 212 left of 5000 (floor 600), resets 14:41 PST in 17m. Refused "run view" (not urgent). If this is a merge, deploy, workflow run or merge-gate read, run it with GH_URGENT=1; otherwise wait for the reset or use a cheaper read.
```

**Floor.** 600 is 12% of 5000: the reserve that makes "urgent always passes" true, since a call that passes the wrapper with nothing left only earns a 403 from GitHub. `GH_BUDGET_FLOOR=<n>` overrides it for one command or one shell.

**The rate read.** The wrapper runs the real `gh api rate_limit --hostname github.com` (free, and it still answers at 0 left) and keeps the answer in `~/.local/state/gh-wrapper/rate.json` (`$XDG_STATE_HOME/gh-wrapper/rate.json`) for 30 seconds. The key is the host plus a hash of `GH_TOKEN` (or `GITHUB_TOKEN`); the token itself is never written. The file is written by temp file and rename. Calls from several machines on one account see each other's spend within 30 seconds. The active account of the real gh is not in the key, so `gh auth switch` can give a wrong answer for at most 30 seconds. A failed or slow read is cached for the same 30 seconds, so an outage costs one wait of up to 3 seconds per half minute and not one per call.

**What it leaves for the log layer** (in `call.notes`):

| Key | Values |
|---|---|
| `urgent` | `write` (the call is a write), `env` (`GH_URGENT=1`), `no` |
| `budget` | `ok`, `refused`, `unread` (the rate read failed: the call passed), `skip` (not github.com), `unchecked` (urgent, a write, `free` or `search`: nothing to decide) |
| `budget_left` | the bucket's remaining calls when this call knew them; a fresh cache entry counts, and the guard reads GitHub only to decide a non-urgent read |

Over-use of `GH_URGENT=1` on reads shows up as `urgent:"env"` in the log.

**Invariants.** It fails open: if the rate read fails, takes over 3 seconds, or returns something unexpected, the call goes on. It never refuses a write, an urgent call, `free` or `search`. It never changes the call's arguments. The floor is an estimate; read the log and set `GH_BUDGET_FLOOR` to what the numbers say.

**Who sets `GH_URGENT=1`.** `ci-main-status --merge-gate` and `--tip` (the cache-and-tags change, PR1). `loop_engine_bump.py`, `agent_kit_bump.py`, `intent-review-check`, `pr-record` and the `pr-body-check` shim set it for every gh call they make (dotfiles #537), and `merge-pr.sh` sets it too (coordinator#882, merged as ba086d75), so the reads on their merge paths are not refused under the floor. Plain `ci-main-status` stays non-urgent, so a refusal there reads as `ERROR cannot read state: ... gh-wrapper: core budget low ...`.

## The budget file

`~/.config/gh-wrapper/budget` holds `on` or `off`, written by the installer from the chezmoi data key `ghBudget.enabled` (`true` or `false`). Default: `on` on `personal`, `off` on `axon-work-computer`. A host with no file runs as off. The log and budget layers and the `gh api` cache are held by this one file. The watch-interval default is not: it runs on every profile (see "Cheaper by default").

## The call log (`gh_log.py`)

Runs only where the budget file says `on` (personal Linux and personal Mac). It writes `calls.jsonl` under `~/.local/state/gh-wrapper/` (under `$XDG_STATE_HOME` when that is set): one JSON line for each gh call, written when the call exits. A watch (`run watch`, or any command given `--watch`) also writes a start line before gh runs, so a watch killed before it exits still leaves a trace.

| Field | Meaning |
|---|---|
| `event` | `exit`, or `start` (watches only; rc and dur_s are null on it) |
| `utc` | UTC time, `2026-11-16T14:41:02Z` |
| `id` | the wrapper's pid: a call's start and exit lines share it |
| `class` | `<group> <verb>` (`pr view`), `api <METHOD> <path>` with ids and shas as `*`, or `unrecognised` |
| `bucket` | `core`, `graphql`, `search` or `free` |
| `urgent` | `write`, `env` (GH_URGENT set) or `no`. Left by the budget layer; null without it |
| `budget` | the budget layer's result: `ok`, `refused`, `unread`, `skip` or `unchecked`. Null without it |
| `budget_left` | calls left in the bucket, when the budget layer knew it. Null without it |
| `action` | `pass`, `rewrite` or `refused` |
| `rewrite` | what a rewrite layer changed, if one did |
| `rc` | the exit code gh returned (or the refusal's code) |
| `dur_s` | seconds from the wrapper's start to exit |
| `who` | `$COORDINATOR_WHO`, else `$GH_CALLER`, else null |
| `parent`, `grandparent` | the calling processes: the program's name, and the file name of the first argument when that argument is an existing file (a script, with or without an extension), e.g. `python3 ci-main-status`. A relative path is looked up in that process's own working directory on Linux, and in the wrapper's on a Mac (no cheap way to read another process's directory there) |
| `cwd` | the working directory |
| `interval` | watches only: the `--interval` gh gets, as a number (30 is 30 seconds) |

Never in a record: arguments, bodies or tokens. The `class` is the command's name, and `parent` and `grandparent` never carry the rest of a command line. A shell that runs gh as `sh -c "<command>"` contributes `sh`.

The budget layer leaves `urgent`, `budget` and `budget_left` in `call.notes`, and this layer writes them as found.

**Rotation.** When the file reaches 5 MB it is renamed to `calls.jsonl.1`, replacing the one before. `GH_WRAPPER_LOG_MAX=<bytes>` sets the size (the tests and the proof use it).

**Failure.** A write that fails is reported on standard error as `gh-wrapper: layer gh_log failed (...); the call goes on`. The call's exit code and output do not change.

**Top callers.** The current file only, exit lines only, so a watch counts once:

```sh
jq -sr 'map(select(.event=="exit")) | group_by(.class,.who) | map({class:.[0].class,who:.[0].who,n:length,secs:(map(.dur_s)|add)}) | sort_by(-.n) | .[:10][] | @json' ~/.local/state/gh-wrapper/calls.jsonl
```

## The work rules (`gh_policy.py`)

Four refusals that keep issues and pull requests in the one agreed form. The layer sits in the wrapper because every `gh` call passes it: an agent's command, `pr-open`, `issue-open`, the bump scripts, a coordinator script, whatever harness started them. The Bash hook's tables decide which route an agent may use (`pr-open`, `issue-open`, the merge gates); this layer decides what that route may send, so no rule is written twice.

| Call | Refused unless | Run instead |
|---|---|---|
| `gh pr create` (`pr new`) | the first line of the body is `Closes #N` or `Refs #N`, and N is an open issue of that repository (not a pull request) | `issue-open`, then `pr-open` |
| `gh pr merge` | no `--merge`, `-m`, `--rebase` or `-r`: every pull request lands as one squash commit | `--squash` |
| `gh issue create` (`issue new`) | the body has the three parts Problem, Wanted and Done when (each a heading line: `## Problem`, `**Problem.**`, `Problem:`), and `--label` holds exactly one of bug, change, flaky test, docs, question (other labels do not count) | `issue-open` |
| `gh issue close` | a merged pull request is linked to the issue (GitHub's own `closedByPullRequestsReferences`), or the call has `--reason "not planned"` and a non-empty `--comment` | close from the pull request, or say why |

gh reads a flag that stands before the group at the command, so `gh -R owner/repo pr merge 5` and `gh --help=false pr merge 5` are `pr merge`: the wrapper moves such flags behind the group (`leading_flags`) before it judges the call, as it does for a group's own repository flag. A leading flag whose extent is not clear (a bare `--flag value`) cannot be placed, so a call with one that names a rule command is refused, not passed. A `--help=false` is not a help request, since gh runs the command. A body file must be a regular file: `/dev/stdin`, a pipe or `<(...)` would be read here and leave gh an empty body, so they are refused. `--duplicate-of` is not a third way to close: a duplicate closes as "not planned" with a comment. `gh pr merge` with no method flag is not refused here (gh asks which method on a terminal); the repository's own merge settings are the other half of the squash-only rule.

The body must be given as text or a file (`--body`, `--body-file FILE`): a body on standard input, or one gh composes (`--fill`, `--template`, `--editor`, `--web`), cannot be read before gh runs, so a call with no `--body` or `--body-file` is refused for `pr create` and `issue create`. With a body given, the text is what is read, and gh's own `--fill` or `--web` only changes how the rest is composed. A call whose flags the wrapper's table does not list is refused for these four commands, as nothing says whether it is a merge commit. `--help` is never refused. The refusal is one sentence on standard error, `gh-wrapper: refused \`gh pr merge\`: ...`, exit 1, and gh does not run. The issue and pull request reads go through the real gh (`gh issue view`, `gh pr view`, never prompting), in the repository `--repo` names, else gh's own choice.

**Switch.** `~/.config/gh-wrapper/policy` says `on` or `off`; the installer writes `on` on `personal` and `off` elsewhere, with no chezmoi data key. A host with no file runs as off. It is its own file, not the budget file: turning the API budget off must not drop a repository rule. The work Mac is left out because these are Michael's own repository rules and an employer's repositories keep their own tracker rules.

**What is excused: one place.** The top of `gh_policy.py` holds the only exemption, from the issue-first rule, recognised by something a tool sets:

- `PR_WITHOUT_ISSUE`: the kinds of pull request that need no issue: release, pin-bump and revert, and nothing else. Each is `(kind, head regex, title regex)`, and a pull request is exempt only when **both** its branch and its title have the form the opening tool gives them, so a hand-made pull request with "release" in its title is still refused. A call with no `--head` or no `--title` is never exempt.

| Kind | Branch | Title | Set by |
|---|---|---|---|
| release | `release/vX.Y.Z` | `release: vX.Y.Z` or `release: prepare vX.Y.Z` | Loop Engine's `release-after-merge.sh`, the agent-kit release |
| agent-kit pin bump | `agent-kit-vX.Y.Z` | `chore(agent-kit): pin @cartwmic/agent-kit <version>` | `agent_kit_bump.py` |
| loop-engine pin bump | `loop-engine-vX.Y.Z` | `feat(loop-engine): import vX.Y.Z skills; bump pins to <version>` | `loop_engine_bump.py` |
| t3 pin bump | `t3-pin/<version>` | `t3 pin: <version>` | `t3_pin_check.py` |
| revert | `revert-<number>[-<branch>]` | `Revert "<original title>"` | GitHub's Revert button |

`--merge` and `--rebase` have no exemption for any caller: the coordinator's `scripts/merge-pr.sh` merges with `--squash`, so a call that sets `GH_CALLER=merge-pr` is judged like every other.


**Log.** Every refusal and every use of an exemption is one line in `~/.local/state/gh-wrapper/policy.jsonl`: `{utc, rule (issue-first, squash-only, issue-form, close-rule), outcome (refused or exempt), class, kind (the exemption used, else null), who ($GH_CALLER, else null)}`. Never a title, a body, an issue number or a repository. Refusals per rule: `jq -sr 'map(select(.outcome=="refused")) | group_by(.rule)[] | "\(.[0].rule) \(length)"' ~/.local/state/gh-wrapper/policy.jsonl`. 

**Failure.** A bug in the layer never stops a call (the seam's rule above); only its own refusal does. When an issue read fails (no network, an unknown number) the `pr create` is refused with the reason, as the link cannot be checked.

**Labels.** `gh issue create --label change` fails at GitHub when the repository has no label of that name, and gh's message names it. The five kind labels are created once per repository with `gh label create <name> -R OWNER/REPO`.

Tests: `python3 -m unittest discover -s tests/leak-guard -p 'test_gh_policy.py'` drives each refusal and each pass-through through the installed layout with a fake real gh; `test_gh_installer.py` checks the policy file per profile.

## Profiles

| Profile | Gets |
|---|---|
| personal Linux | the wrapper, mise and shell PATH, the budget file `on`, the policy file `on` |
| personal Mac | the same; PATH through mise and `.zshenv` |
| personal Linux, container mode (the agent host pod) | the same wrapper, lib, budget `on` and policy `on`; PATH through `.zshenv`, `.zprofile`, the mise file and the link `~/.local/bin/gh` (the image's PATH starts with `~/.local/bin`) |
| work Mac | the same wrapper at the new path, leak-guard checks unchanged, the budget file `off`, the policy file `off` (no work rules), and the watch-interval default (`gh run watch` and `gh pr checks --watch` poll every 60 s; Michael's decision #3242 on ask #1207). No log, no budget guard, no `gh api` cache there: a per-call log of directory and parent process, and refusing reads, are new on an employer machine, so Michael is asked before they are turned on there. |

## Tests

`python3 -m unittest discover -s tests/leak-guard`: `test_gh_budget.py` drives the budget guard through the installed layout with a fake real gh that answers `api rate_limit` from the environment; `test_gh_layers.py` drives the classification, the exempt set and the seam through the installed layout (`bin/gh` next to `lib/`) with a fake real gh and fake layer modules; `test_gh_log.py` the call log's record and file through the installed wrapper; `test_gh_rewrite.py` the rewrite layer (below); `test_gh_installer.py` runs the real template; `test_gh_path.py` the shells; `test_gh_wrapper.py` the leak-guard checks, unchanged.

## Cheaper by default (`gh_rewrite.py`)

Rewrites a call the caller did not ask to change. `plan()` is pure: the arguments in, the arguments out. The layer's `before` hook applies it.

| Call | Rewrite | Runs on |
|---|---|---|
| `gh run watch`, with no `-i` or `--interval` | `--interval 60` | every profile, the work Mac included (Michael's decision #3242 on ask #1207) |
| `gh pr checks --watch`, with no `-i` or `--interval` | `--interval 60` | every profile |
| a non-urgent `gh api` GET read on the core or search bucket | `--cache 15s` | where the budget file says `on` (personal) |

The cache rewrite is skipped for a call that names a method other than GET, sends fields (`-f`, `-F`, `--field`, `--raw-field`) or a body (`--input`), already has `--cache`, asks for help, or has no endpoint. `gh api rate_limit` (free) and GraphQL (`api POST graphql`) are never touched. `GH_URGENT=1` keeps a read fresh. Writes are never rewritten.

A caller's `-i` or `--interval` is honoured and never clamped; for a repeated flag the last value counts, as gh keeps it. A call whose flags cannot be read (an unknown flag, a value flag with no value) is left as it is.

Why 60 seconds: each `gh run watch` poll is about 4 REST calls, so the default 3-second poll costs about 64 calls a minute per watcher (measured: 16 polls in 60 seconds). The design had 30; 60 matches the agents' waiting rule. Why 15 seconds: `gh api --cache` is a plain time-to-live file cache. A second read of the same URL inside the window makes no network call. The cache key includes the request headers: a raw-`Accept` read of a file URL was not served the cached JSON for the same URL.

What it exposes for the log layer: `call.action` is `rewrite` and `call.rewrite` is `interval 60` or `cache 15s` when the call changed. `call.notes["interval"]` is set on every watch call (`run watch`, and `pr checks --watch`): the interval gh polls at, the caller's own or the default, as an int when it is a number. The log layer should record `rewrite` and `interval` from these.

Leak-guard sees the arguments after the rewrite: `checked_run` takes `call.args` after the layers ran, and `test_gh_rewrite.py` checks it with a test-only layer that adds text to a guarded comment. This layer's rewrites add flags to reads only, which leak-guard does not check, so no rewrite of this layer can change a guard verdict.

Tests: `python3 -m unittest discover -s tests/leak-guard -p 'test_gh_rewrite.py'`. The planning is tested as pure functions on the wrapper's own parse, and the installed wrapper is run with the budget on, off and missing. The layer has no flag table: the wrapper parses `run watch`, `pr checks` and `gh api` with its `FLAGS` rows (`FOR_LAYERS` in `scripts/gh-wrapper`) and hands the result in as `call.parsed`. The tests fail when a watch row is missing from `FLAGS`, and when a flag added to a row is not read.
