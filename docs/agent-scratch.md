# Agent scratch on the Workshop SSD

Agent scratch (work dirs, review checkouts, build targets, dumps) fills the internal disk. This puts it on the Workshop SSD. Personal Mac only: `/Volumes/Workshop` exists nowhere else (row in [profiles.md](profiles.md)). Plan and numbers: the owner's ask 659, "All recommended".

## What is installed

| Piece | Where | Does |
|---|---|---|
| `dot_config/agent-scratch/workshop.env` | `~/.config/agent-scratch/workshop.env` | Sets `AGENT_TMP=/Volumes/Workshop/macbook/tmp-home`. |
| one line in `dot_zshenv` | `~/.zshenv` | Sources that file if it exists. Every zsh reads it, so T3, Claude Code and Pi shells get `AGENT_TMP`. On the work profile the file is not deployed and the line does nothing. |
| `run_onchange_after_81_agent_scratch_workshop.sh` | runs on `chezmoi apply` | Makes `/Volumes/Workshop/macbook/tmp-home`. Moves nothing. |
| `dot_local/user_scripts/executable_agent_tmp_move.py` | `~/.local/user_scripts/agent_tmp_move.py` | Moves idle `~/tmp` subtrees to `AGENT_TMP`. Dry run by default. |

New scratch goes under `$AGENT_TMP`. `~/tmp` stays as the name every note, ledger entry and qmd collection already uses: each subtree that moves leaves a link at its old path, and once everything has moved `~/tmp` itself becomes a link.

## Workshop not mounted

Nothing falls back to the internal disk.

- A new shell prints one line on stderr (`agent-scratch: /Volumes/Workshop is not mounted ...`) and still sets `AGENT_TMP` to the Workshop path. Child shells stay quiet.
- A write under `$AGENT_TMP` fails with an error: `/Volumes` is root-owned, so no user process can recreate the path on the internal disk.
- `81_agent_scratch_workshop.sh` exits 1 and creates nothing. `agent_tmp_move.py` stops before changing anything.
- Every `~/tmp/<name>` link dangles until the disk is back.

## Moving what is already in `~/tmp`

Many agents have live worktrees and scratch in `~/tmp`. So: ship `AGENT_TMP` first (new work lands on Workshop), then move only what is idle.

    agent_tmp_move.py                    # dry run: WOULD MOVE / HOLD <reason> per top-level entry
    agent_tmp_move.py --apply            # move the ones that qualify, one at a time
    agent_tmp_move.py --apply --only NAME [NAME ...]
    agent_tmp_move.py --finish           # can ~/tmp itself become a link? (dry run)
    agent_tmp_move.py --finish --apply

An entry moves only if it is not a link, is not on the keep list (`ssd-move`, `ssd-scratch`, `--keep NAME`), has nothing open in it (an `lsof` snapshot taken right before the move, checked against the old and the new path; a process whose current directory is inside it counts), has a newest mtime older than 2 hours (`--min-age-hours`), and holds no registered git worktree and is not inside one (`git worktree list` of the repos under `/Volumes/Workshop/macbook/git`, `~/.local/share/chezmoi` and `~/.t3/worktrees/*/*`).

The copy is `rsync -a` into `$AGENT_TMP/.NAME.partial`. It is checked (entry count, file bytes, and that the source did not change while copying), `lsof` is looked at once more, then the partial is renamed to `$AGENT_TMP/NAME`, the original is renamed aside, a link takes its place and the renamed original is removed. Nothing is removed before the check passes. A failure leaves the original in place and the partial copy; a rerun syncs into it again (`rsync --delete` inside the partial only), so a stale partial does not block the entry. Each decision of an `--apply` run (moved, held, failed, with the reason) is a line in `~/.local/state/agent-tmp-move/moves.jsonl`.

`--finish` replaces `~/tmp` with a link to `$AGENT_TMP`, only when every entry of `~/tmp` is already a link into `$AGENT_TMP` and no process has `~/tmp` itself as its current directory. The old directory of links is renamed `~/tmp.links-old-<time>`, not deleted.

**Reproduce:** `chezmoi apply`, then run the script with `--apply` again whenever more subtrees have gone idle.

**Undo one entry:** `rm ~/tmp/NAME` (the link), then `rsync -a $AGENT_TMP/NAME/ ~/tmp/NAME/` and check it before removing the Workshop copy. **Stop using Workshop for new work:** remove `dot_config/agent-scratch` and the `dot_zshenv` line from the source and apply (editing `~/.zshenv` by hand is undone by the next apply). Moved subtrees stay on Workshop behind their links. **Undo `--finish`:** `rm ~/tmp` (the link) and `mv ~/tmp.links-old-<time> ~/tmp`.

## What stays internal

The coordinator ledger and daemon state, T3's own sqlite and userdata, the qmd index, sockets, `~/.local/share/agent-traces`, mise installs and shims, rustup and `~/.cargo` registry. End-to-end test and journey scratch stays in `/tmp`: never set a global `TMPDIR` to Workshop, because socket paths have a ~104-byte limit.

## Launchd jobs

Background jobs reach Workshop through the mise route (the macOS privacy grant for removable volumes is held by mise). `qmd-refresh` reads `~/tmp/*/*.md`; after a subtree moves, the read goes through the link. Prove it with `launchctl kickstart gui/$(id -u)/local.qmd-refresh` and read `~/Library/Logs/qmd-refresh/`.
