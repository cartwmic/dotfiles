# inspect-prompt agent instructions

## Scope and authority

This file applies when working in the `inspect-prompt` extension directory.
The repo-root `AGENTS.md` owns chezmoi source, apply, and Git rules; the
Pi-global guide owns cross-project habits. The parent extensions README owns
shared extension conventions. [README.md](./README.md) explains what the two
snapshot commands do for a user. Keep this file on extension-specific work.

The chezmoi source is `dot_pi/private_agent/extensions/inspect-prompt/`.
Edit it in the source checkout. The deployed copy lives under
`~/.pi/agent/extensions/inspect-prompt/` and is generated. The `termux`
profile skips Pi; `personal` and `axon-work-computer` receive the extension.

## Workflow

Keep the two paths distinct: `/inspect-prompt` reads the assembled system
prompt and works only while Pi is idle; `/inspect-session` and Ctrl+Alt+E read
the active branch plus progress already visible in the UI and work during
streaming. The latter must exclude system instructions and abandoned branches.
Use the per-call `ctx` supplied to handlers; storing an `ExtensionContext` for
a later invocation makes it stale after session replacement or reload.

The conversation reader in `session.ts` uses Pi 0.87.1's private fullscreen
component layout to capture pending and chat `!` output. Keep its unsupported-
layout error fail-closed. Saved Bash results and live components can overlap;
reconcile by command/output occurrence, keeping running output and new
repeated commands after compaction. Match a completed pending component only
to a saved result after the latest user message. Changes to that logic need
both focused tests and an actual editor receipt. Leave Herdr's non-Pi
`prefix+e` binding alone; Ctrl+Alt+E is the Pi shortcut.

## Validation

From the chezmoi source root, run the focused tests and both private-session
journeys after edits to snapshot or shortcut behavior:

```sh
(cd dot_pi/private_agent/extensions/inspect-prompt && node --test)
python3 dot_pi/private_agent/extensions/inspect-prompt/scenario.py
python3 dot_pi/private_agent/extensions/inspect-prompt/herdr-scenario.py
```

`scenario.py` uses installed Pi, a scripted provider, a dummy editor, and a
private Herdr client. Its shortcut must reach Pi through that client. Inspect
its outcome and editor receipts; a unit test of `buildConversationSnapshot`
alone cannot prove the user path. `herdr-scenario.py` checks non-Pi pane
navigation and `prefix+e` independently. The private Pi journey currently
exercises only `/inspect-session`. For an `/inspect-prompt` change, extend that
isolated journey or collect an equivalent real Pi TUI command-to-dummy-editor
receipt. Check assembled prompt content, editor return, and no submitted user
query before calling that path validated.

`scenario.py` pins Pi 0.87.1 and Herdr 0.9.1; `herdr-scenario.py` pins Herdr
0.9.1. A version mismatch reports BLOCKED before testing. Check the upgraded
Pi layout and Herdr key route, adapt the pins and fixtures after verifying
compatibility, then rerun. A BLOCKED result is no validation.

Before any separately approved rollout, preview the exact worktree source from
the checkout root:

```sh
chezmoi --source "$PWD" apply --dry-run --verbose "$HOME/.pi/agent/extensions/inspect-prompt"
```

Apply only with the user's approval. Starting a new Pi process is required to
load changed extension code. Do not restart or hand off the owner's Herdr
server for documentation or validation work. Keep disposable scenario servers
and artifacts separate from the owner's session.

## Completion and handoff

Report the changed source paths, focused tests, both journey outcomes (or why
a journey could not run), the target-profile dry-run, and whether anything was
applied or committed. For changes to `/inspect-prompt`, include its real
command-path editor receipt; disclose its absence as unverified. Name any
untested installed Pi/Herdr version or pending rollout step. A successful
script with a dummy editor and provider does not establish behavior with a
real model or a physical keyboard.
