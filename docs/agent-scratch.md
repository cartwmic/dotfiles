# Agent scratch on the Workshop SSD

Agent scratch (work dirs, review checkouts, build targets, dumps) fills the internal disk. This puts it on the Workshop SSD. Personal Mac only: `/Volumes/Workshop` exists nowhere else (row in [profiles.md](profiles.md)). Plan and numbers: the owner's ask 659, "All recommended".

## What is installed

| Piece | Where | Does |
|---|---|---|
| `dot_config/agent-scratch/workshop.env` | `~/.config/agent-scratch/workshop.env` | Sets `AGENT_TMP=/Volumes/Workshop/macbook/tmp-home` and `NPM_CONFIG_CACHE=/Volumes/Workshop/macbook/cache/npm`. |
| one line in `dot_zshenv` | `~/.zshenv` | Sources that file if it exists. Every zsh reads it, so T3, Claude Code and Pi shells get `AGENT_TMP` and `NPM_CONFIG_CACHE`. On the work profile the file is not deployed and the line does nothing. |
| `run_onchange_after_81_agent_scratch_workshop.sh` | runs on `chezmoi apply` | Makes `/Volumes/Workshop/macbook/tmp-home` and `/Volumes/Workshop/macbook/cache`. Moves nothing. |
| `dot_local/user_scripts/executable_agent_tmp_move.py` | `~/.local/user_scripts/agent_tmp_move.py` | Moves idle `~/tmp` subtrees to `AGENT_TMP`. Dry run by default. |
| `dot_local/share/agent-scratch/bin/executable_cargo`, a block in `dot_zshenv` | `~/.local/share/agent-scratch/bin/cargo` | A `cargo` for agent shells only that gives each project its own target dir under `AGENT_TMP` (section below). |

New scratch goes under `$AGENT_TMP`. `~/tmp` stays as the name every note and ledger entry already uses (qmd is the exception: it does not follow links, see "Launchd jobs"): each subtree that moves leaves a link at its old path. `~/tmp` itself stays a real directory holding those links and is not meant to become a link: the qmd config (docs/qmd.md) is the same in every state only while it is a directory.

## Workshop not mounted

Nothing falls back to the internal disk.

- A new shell prints one line on stderr (`agent-scratch: /Volumes/Workshop is not mounted ...`) and still sets `AGENT_TMP` to the Workshop path. Child shells stay quiet.
- A write under `$AGENT_TMP`, a `cargo` target dir or the npm cache fails with an error: `/Volumes` is root-owned, so no user process can recreate the path on the internal disk.
- `81_agent_scratch_workshop.sh` exits 1 and creates nothing. `agent_tmp_move.py` stops before changing anything.
- Every `~/tmp/<name>` link, and the moved `~/.npm/_cacache` and `~/.npm/_npx` links, dangle until the disk is back.

## Moving what is already in `~/tmp`

Many agents have live worktrees and scratch in `~/tmp`. So: ship `AGENT_TMP` first (new work lands on Workshop), then move only what is idle.

    agent_tmp_move.py                    # dry run: WOULD MOVE / HOLD <reason> per top-level entry
    agent_tmp_move.py --apply            # move the ones that qualify, one at a time
    agent_tmp_move.py --apply --only NAME [NAME ...]

An entry moves only if it is not a link, is not on the keep list (`ssd-move`, `ssd-scratch`, `--keep NAME`), has nothing open in it (an `lsof` snapshot taken right before the move, checked against the old and the new path; a process whose current directory is inside it counts), has a newest mtime older than 2 hours (`--min-age-hours`), copying it leaves at least 100 GB free on Workshop (`--reserve-gb`, checked with `df` right before each copy, so the agent-kit gate runner's temporary use of up to ~60 GB still fits), and holds no registered git worktree and is not inside one (`git worktree list` of the repos under `/Volumes/Workshop/macbook/git`, `~/.local/share/chezmoi` and `~/.t3/worktrees/*/*`).

The copy is `rsync -a` into `$AGENT_TMP/.NAME.partial`. It is checked (entry count, file bytes, and that the source did not change while copying), `lsof` is looked at once more, then the partial is renamed to `$AGENT_TMP/NAME`, the original is renamed aside, a link takes its place and the renamed original is removed. Nothing is removed before the check passes. A failure leaves the original in place and the partial copy; a rerun syncs into it again (`rsync --delete` inside the partial only), so a stale partial does not block the entry. Each decision of an `--apply` run (moved, held, failed, with the reason) is a line in `~/.local/state/agent-tmp-move/moves.jsonl`.

**Reproduce:** `chezmoi apply`, then run the script with `--apply` again whenever more subtrees have gone idle.

**Undo one entry:** `rm ~/tmp/NAME` (the link), then `rsync -a $AGENT_TMP/NAME/ ~/tmp/NAME/` and check it before removing the Workshop copy. **Stop using Workshop for new work:** remove `dot_config/agent-scratch` and the `dot_zshenv` line from the source and apply (editing `~/.zshenv` by hand is undone by the next apply). Moved subtrees stay on Workshop behind their links. 

## Caches

| Cache | Setting | Where it lands |
|---|---|---|
| npm | `NPM_CONFIG_CACHE` in `workshop.env` (no `~/.npmrc` is shipped) | `/Volumes/Workshop/macbook/cache/npm` |

A cache only, so every shell shares it. Every zsh reads `~/.zshenv`, so a terminal gets the variable too; to use the internal npm cache, `unset NPM_CONFIG_CACHE` in `~/.zshenv.local`. Unmounted: npm fails on the Workshop path; there is no fallback.

uv (10.6 GB) and cargo are not set here yet. uv's `cache-dir` waits until its cache can be moved (a running `uvx` process holds it), so nothing creates the new directory first. cargo: a single `CARGO_TARGET_DIR` for every shell and project would make workspaces share one target dir, and a per-project path cannot be expressed in an environment variable (cargo expands `{workspace-root}` only in a config file).

The existing npm cache was moved with the same script (the age check is off, a cache is always being touched; the old path became a link, so a tool that ignores the setting still lands on Workshop):

    mkdir -p /Volumes/Workshop/macbook/cache/npm
    agent_tmp_move.py --apply --source ~/.npm --dest /Volumes/Workshop/macbook/cache/npm --only _cacache _npx --min-age-hours 0

Undo: `rm ~/.npm/_cacache` (the link) and `rsync -a` the directory back; the same for `_npx`. (`npx` keeps its cache in `<npm cache>/_npx`, so the moved `_npx` is the live one.)

## What stays internal

The coordinator ledger and daemon state, T3's own sqlite and userdata, the qmd index, sockets, `~/.local/share/agent-traces`, mise installs and shims, rustup and `~/.cargo` registry. End-to-end test and journey scratch stays in `/tmp`: never set a global `TMPDIR` to Workshop, because socket paths have a ~104-byte limit.

## Launchd jobs

Background jobs reach Workshop through the mise route (the macOS privacy grant for removable volumes is held by mise). `qmd-refresh` reads the notes; qmd does not follow links, so it cannot read a moved subtree through `~/tmp/<name>`. The qmd `notes` collection reads `/Volumes/Workshop/macbook/tmp-home` and `notes-internal` reads what is still a real directory in `~/tmp` (docs/qmd.md, "The notes collections and the Workshop SSD"). Prove a change with `launchctl kickstart gui/$(id -u)/local.qmd-refresh`, read `~/Library/Logs/qmd-refresh/`, and check that `qmd status` still shows the `notes` file count.

## cargo target directories (agent shells only)

An agent shell is one where `CLAUDECODE` (Claude Code) or `T3CODE_THREAD_ID` (T3 Code) is set. There `dot_zshenv` puts `~/.local/share/agent-scratch/bin` on `PATH` just before `~/.cargo/bin` (other entries such as bun, gvm and mise can still come earlier), after `~/.cargo/env`, and its `cargo` sets `CARGO_TARGET_DIR=$AGENT_TMP/cargo-target/<name>` and runs the real cargo. `<name>` is the git top-level directory's name (or the current directory's name outside git), so each project gets its own target directory and projects do not rebuild each other's work or fight over one lock. An existing `CARGO_TARGET_DIR` (or `CARGO_BUILD_TARGET_DIR`) is left alone, so a brief that names one still wins.

Why a wrapper: a target directory per project cannot be set in an environment variable, because the variable is fixed when the shell starts and cargo expands `{workspace-root}` only in config files. The only global config file is `~/.cargo/config.toml`, which stays unmanaged. A terminal never sees the wrapper, so hand builds stay on the internal disk. (Unverified: whether T3's own built-in terminal sets `T3CODE_THREAD_ID`; if it does, a hand terminal inside T3 gets the wrapper too.)

Where the build output is: in an agent shell a build no longer lands in `./target`. Ask cargo: `cargo metadata --format-version 1 --no-deps | jq -r .target_directory`, or read `$CARGO_TARGET_DIR`. A script or README that runs `target/debug/<bin>` must use that directory. Each worktree has its own directory (named by its top-level directory) and they are not cleaned up when a worktree is deleted; the wrapper also overrides a project's own `build.target-dir` (none of the local repos sets one).

Claude Code runs each tool call from a snapshot of `PATH` taken when the session starts, and that snapshot replaces what `~/.zshenv` set. A session that started before the wrapper was applied therefore calls the real cargo directly (a child `zsh -c` still gets the wrapper); check a fresh session with `command -v cargo`. Until that is confirmed, name `CARGO_TARGET_DIR=$AGENT_TMP/cargo-target/<repo>` explicitly in builder briefs.

Not covered: Pi and standalone Codex shells have no marker that was verified, so their builds stay internal until a brief sets `CARGO_TARGET_DIR=$AGENT_TMP/cargo-target/<repo>`. Unmounted Workshop: the target is under the missing Workshop path and cargo fails with an error; there is no fallback. Timing (clean `cargo build --offline` of loop-engine, one run each): 116 s with the target on the internal disk, 91 s on Workshop. Undo: remove the wrapper directory and the `PATH` block in `dot_zshenv`, then apply.
