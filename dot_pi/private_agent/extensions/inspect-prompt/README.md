# inspect-prompt

## Overview

This Pi extension opens local, read-only editor snapshots of two different
things: the assembled system prompt and the current conversation. Use the
first to see the instructions Pi loaded. Use the second to read or search the
conversation while an answer is still streaming. Editor changes are discarded.

The extension is managed from this chezmoi source tree on the `personal` and
`axon-work-computer` profiles. Termux skips Pi. Its agent-facing procedure is
in [AGENTS.md](./AGENTS.md).

## Setup

Pi needs an interactive TUI and an external editor. `/inspect-session` also
requires fullscreen mode (`tuiMode: "fullscreen"`). Managed settings now use
regular mode on both desktop profiles. To use the conversation reader, change
`dot_pi/private_agent/private_settings.json.tmpl`, apply
`~/.pi/agent/settings.json` after approval, and start a new Pi process.
The project `.pi/settings.json` `externalEditor` key takes precedence over
the Pi-global key. If neither supplies a usable command, it tries `$VISUAL`,
`$EDITOR`, then `nano` (or `notepad` on Windows). The editor command is split
on spaces, so an executable path containing spaces needs a wrapper on `PATH`.

From the chezmoi source root, preview the managed destination:

```sh
chezmoi --source "$PWD" apply --dry-run --verbose "$HOME/.pi/agent/extensions/inspect-prompt"
```

After approval to roll out the source, apply that destination and start a new
Pi process:

```sh
chezmoi --source "$PWD" apply "$HOME/.pi/agent/extensions/inspect-prompt"
pi
```

Applying does not restart the owner's Herdr server. This repository's
`AGENTS.md` owns apply and conflict procedure; an edit to this README alone
does not authorize a live apply.

## Usage

`/inspect-prompt` opens Pi's assembled system prompt at invocation time,
including loaded agent instructions and skills. It works when Pi is idle. The
file is a snapshot of `ctx.getSystemPrompt()`, so provider-side per-request
rewrites are outside its scope. The command does not submit a query. When Pi
is busy it reports that the prompt is available once the agent is idle.

`/inspect-session` or **Ctrl+Alt+E** opens the active conversation even while
Pi streams. It includes saved messages on the current branch, visible
assistant/tool progress, compaction summaries, and displayed or pending user
`!` / `!!` Bash output. Completed and running Bash output is reconciled so a
repeated command after compaction still appears without a duplicate of the
same execution. The snapshot excludes system instructions, internal thinking,
and abandoned branches. It stays fixed while the editor is open; closing the
editor returns to the same Pi session without applying any edits.

Ctrl+Alt+E is Pi-specific. Herdr's `prefix+e` continues to open scrollback for
a selected non-Pi pane.

## Validation

From the chezmoi source root, run the focused tests and the private-session
journeys after changing snapshot or shortcut behavior:

```sh
(cd dot_pi/private_agent/extensions/inspect-prompt && node --test)
python3 dot_pi/private_agent/extensions/inspect-prompt/scenario.py
python3 dot_pi/private_agent/extensions/inspect-prompt/herdr-scenario.py
```

`scenario.py` launches installed Pi in a private Herdr 0.9.1 client, with a
scripted provider and dummy editor. It routes Ctrl+Alt+E through that client,
checks eight editor receipts, and observes a scrolled-up passage during
assistant-text and tool streaming. The receipts cover partial output,
running and post-settlement Bash output, repeated commands after compaction,
branch exclusion, editor return, and a subsequent Pi turn. Bottom-follow is
checked separately. The script writes an `outcome.json` and editor receipts;
pass `--artifact-dir PATH` to keep them in a chosen directory.

`herdr-scenario.py` checks tab/pane navigation and the actual non-Pi
`prefix+e` editor dispatch in its own Herdr session. Its scrollback receipt
contains the selected pane's ordered markers once and omits markers from the
other pane and tab. Both scripts clean up only their private sessions. The
journeys exercise installed Pi and Herdr processes with a dummy editor and
scripted model; they do not prove a live apply, real-model behavior, or
physical-keyboard delivery. The Pi journey currently exercises
`/inspect-session`. For a change to `/inspect-prompt`, also require a real
Pi TUI command-to-dummy-editor receipt showing the assembled prompt, editor
return, and no submitted query; the agent procedure in [AGENTS.md](./AGENTS.md)
sets that completion boundary.

## Limits and troubleshooting

The conversation reader depends on Pi 0.87.1's private fullscreen component
layout for live Bash output. An unsupported-layout error can also mean Pi
is in inline mode; set `tuiMode` to `fullscreen` and start a new Pi process.
If a Pi upgrade changes the fullscreen layout, `/inspect-session` stops before
opening the editor. `scenario.py` pins Pi 0.87.1 and Herdr 0.9.1; `herdr-scenario.py` pins
Herdr 0.9.1. On another version, they report BLOCKED before exercising the
editor. Check the changed layout or key route, update the reader and test
pins/fixtures after verifying compatibility, then rerun the private journeys.
BLOCKED is no validation. The snapshot is local and temporary; it cannot
follow edits or serve as a saved transcript.

If `/inspect-prompt` does nothing during a turn, wait for Pi to become idle.
If it reports "Opened" but no editor appeared, its current command path did
not surface a spawn failure; check the editor command or use `/inspect-session`
to get a launch error. If `/inspect-session` reports that it needs an
interactive TUI, start Pi interactively; `pi --print` has no editor UI. For an
editor launch error, check the configured command before blaming the shortcut. If the command works but Ctrl+Alt+E does not arrive through Herdr,
run `scenario.py` on its pinned Pi/Herdr versions to inspect the client route.
