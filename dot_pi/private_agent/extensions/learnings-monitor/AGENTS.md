# Learnings monitor — agent instructions

## Scope

This file applies to `dot_pi/private_agent/extensions/learnings-monitor/` in
the public `cartwmic/dotfiles` chezmoi source, including linked worktrees. Edit
source here. Chezmoi deploys it to `~/.pi/agent/extensions/learnings-monitor/`
on the personal and work profiles. The operator's opportunities, checkpoints,
and native observer sessions stay in local data and Pi session directories.
Keep those records and any secrets out of this source tree.

## Authority

The repo-root `AGENTS.md` controls chezmoi mapping, profile gates, secrets,
live apply, and Git decisions. The Pi-global `~/.pi/agent/AGENTS.md` supplies
cross-project habits. This file covers the extension's code and proof paths.
Use [README.md](./README.md) for operator setup and commands;
[core/README.md](./core/README.md) defines the source-neutral producer contract.
The shared `dot_pi/private_agent/extensions/README.md` owns Pi extension
lifecycle conventions. These files have different scopes; keep their contents
in their owning documents.

## Workflow

Choose the owner of a change before editing. Put evidence, proposal identity,
dismissal, and cross-source rules in the portable core. Keep Pi session capture,
model routing, storage, and commands in the adapter. The core must work without
Pi, Hindsight, or filesystem imports. Records passed from other sources cannot
become an alias for the current source's dismissed proposal.

Use each event or command's current `ExtensionContext`. A saved `ctx` becomes
stale after session replacement or reload. Capture settled exchanges into the
durable queue before advancing a checkpoint; preserve pending work on exit and
`/learnings off`. A worker may inspect files with `read`, `grep`, `find`, and
`ls`. Keep shell and mutation tools out of its allowlist. Hindsight matches are
possible analogues; local evidence alone supports a recurrence claim. Preserve
operator edits to opportunity Markdown and the dismissal history.

From the dotfiles checkout root, check the Pi CLI and the SDK installed for
the active Node version before running the worker tests:

```sh
command -v pi
test -f "$(npm root -g)/@earendil-works/pi-coding-agent/dist/index.js"
```

If Pi is missing after the root setup, ask before the persistent
`mise run install-pi` task (Node/npm must exist first). That task skips when
any `pi` executable is on PATH. If `pi` exists but the active Node lacks the
SDK, ask before this persistent install into the active Node, then recheck
both prerequisites:

```sh
npm install -g @earendil-works/pi-coding-agent
command -v pi
test -f "$(npm root -g)/@earendil-works/pi-coding-agent/dist/index.js"
```

Check that the `pi` command resolves through the intended Node installation;
fix a stale PATH before the full Pi proof. Follow the repo-root Pi-patch
procedure after reinstalling the package. Supply the active global module
root to tests when Node does not find global packages by default:

```sh
NODE_PATH="$(npm root -g)" node --test dot_pi/private_agent/extensions/learnings-monitor/*.test.mjs dot_pi/private_agent/extensions/learnings-monitor/core/*.test.mjs
python3 tests/learnings-monitor/proof.py --core-only
```

The focused real-key reviewer proof is `python3 tests/learnings-monitor/ui-proof.py --scenario stage`; the final matrix uses `--scenario all` (stage, promotion, scope-time). It must pair actual pane navigation with authoritative Markdown and scripted request counts, and check primary conversation coherence. Do not replace keys with private review calls or add command aliases/debug dumps for proof.

The scope/time scenario chooses sources by their displayed chooser labels, not fixed indices. It asserts older/newer local date and age, unknown legacy dates, and the unchanged date after Apply/reopen. Resize uses the standard PTY window-size ioctl and waits for native redraw. Fixture ordering may guide navigation keys only within the active status filter. Verify the source-qualified selected record and its recorded date in fresh native output after the scope/filter action; a header or an earlier cumulative pane match is not a completed detail frame.

The read-only worktree deployment preflight is `python3 tests/learnings-monitor/source-preview.py`. It independently hashes rendered and live files, checks mapping and targeted dry-runs, and never applies. It fails closed when hook safety or owner 1Password access is unavailable. Tests remain source-only and ignored. Ask before any live deployment.

The full private-PTY Pi journey and isolated work-profile render use the
commands in [README.md](./README.md) under Validation. Run the completed Pi journey after behavior changes; a
passing core seam test cannot establish that status, resume, or review works
through the operator path. Recheck the personal destination with the
repo-root `AGENTS.md` dry-run procedure. The profile render applies only in a
disposable HOME and confirms the work Hindsight bank. It does not change the
operator's HOME.

Ask before a live chezmoi apply, a commit or push, or deletion of a real
source's local notes through `/learnings cleanup`. Disposable test roots may
clean up their own files. The broad read-only file-access risk and lack of a
spending cap are owner-accepted boundaries; changing either needs a new owner
decision. Markdown instructions are advisory. The read-tool allowlist, source
isolation, and cleanup ownership still need executable checks.

## Completion and handoff

Name the source files changed, the component and completed Pi proof outcomes,
the targeted chezmoi dry-run and isolated work-profile result, and any check
you could not run. State whether live apply, source cleanup, staging, commit,
or push occurred. Give the operator paths to remaining local data and any
pending batches that still need review. Scripted model and Hindsight endpoints
prove the isolated path; report live-service behavior separately when it was
actually exercised.
