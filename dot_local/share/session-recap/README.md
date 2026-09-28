# session-recap

## Overview

`session-recap` is a portable stdin-to-command recap CLI. It works without Pi or
Herdr, accepts a configured executable argv (no shell), and writes dated records
outside either application. The CLI needs Python 3.11+ (`tomllib`). Its wrapper
uses `SESSION_RECAP_PYTHON` when set, then a compatible `python3` on `PATH`, then
an available user-managed mise shim. This matters when a Herdr-hosted Pi shell
exposes macOS's older `/usr/bin/python3`. The CLI and Python implementation live
at `dot_local/bin/executable_session-recap` and
`dot_local/share/session-recap/session_recap.py` in chezmoi source. Use
`create` for standalone single or group recaps; Pi and Herdr use the
prompt/prepare/publish commands. The CLI runs on demand and requires a
configured recap command. This repository does not bundle a model or recap
service.

## Setup

From a desktop with chezmoi initialized, preview and apply the CLI and its
configuration:

```sh
chezmoi apply --dry-run --verbose ~/.local/bin/session-recap ~/.local/share/session-recap ~/.config/session-recap
chezmoi apply ~/.local/bin/session-recap ~/.local/share/session-recap ~/.config/session-recap
```

Desktop chezmoi profiles `personal` and `axon-work-computer` deploy the config
template and editable prompts to `~/.config/session-recap/`:

- `config.toml` — profile default command (`claude -p` for both desktop profiles)
- `single-prompt.md` — `[[LABEL]]` and `[[TEXT]]`
- `group-prompt.md` — `[[LABEL]]` and `[[MEMBERS]]`

The default command needs an installed, authenticated Claude CLI. For another
stdin-to-stdout recap program, create the host-local, unmanaged
`~/.config/session-recap/config.local.toml`:

```toml
command = ["/path/to/my-recap-command", "--stdin"]
```

The argv runs directly without a shell. The rendered prompt is sent on
stdin; successful nonblank UTF-8 stdout is the recap. Exit failure, invalid
UTF-8, and blank output are recorded as failed attempts and do not replace the
last successful recap. Termux does not deploy the desktop command/config; it is
an SSH client. Its phone-side review library is separate.

## Usage

A single input does not require a label:

```sh
printf '%s\n' 'Recent changes and the present state.' |
  session-recap create --kind single
```

A successful command prints the record ID. Find its published summary under
`~/.local/share/session-recap/records/YYYY-MM-DD/` (or the selected
`$XDG_DATA_HOME`); the CLI does not print the recap text.

A related group accepts optional labels and retains member record IDs when
provided:

```sh
printf '%s\n' '{"members":[{"label":"parser","text":"Parser work is complete."},{"text":"Migration is next."}]}' |
  session-recap create --kind group --label "Release preparation"
```

The same group command supports coordinator-owned sources such as a workspace
or the active Herdr session. Pi integrations use `prepare` and `publish` so
native pane/workspace attribution is attached immediately before publication.
The overview only reads those published records; it never chooses a command or
generates a summary.

## Storage and history

By default, user-local data is stored under
`~/.local/share/session-recap/` (or `$XDG_DATA_HOME/session-recap/`):

```text
records/YYYY-MM-DD/<record-id>.json   # dated published recaps and failures
latest.json                            # latest-success and last-attempt index
prepared/<record-id>.json              # unpublished Pi preparation
prompts/<encoded-session-id>.json      # current Pi prompt, separate from recap
```

Dated records are the history and survive process or Herdr restarts. The latest
index can point to a failed attempt while preserving its prior successful
record. Current prompts are not recaps. They are published by the Pi input hook
while work is in progress; successful settled-response recaps are a separate
publication. `prompt rekey --session-id ID --from-pane-id OLD --pane-id NEW`
reads the expected prompt text from stdin and changes only a matching current
prompt under the store lock. It preserves the working state and does not
replace a newer input while a prior response waits to publish.

## Troubleshooting

- `python3` is too old: the CLI requires Python 3.11+; set
  `SESSION_RECAP_PYTHON` to a compatible interpreter or make one available
  through mise.
- The default backend exits or prints nothing: authenticate the Claude CLI
  used by `claude -p`, or set `command` in host-local `config.local.toml` to
  an available stdin-to-stdout program. The failed attempt stays in history
  and the last good recap remains indexed.
- No Herdr overview recap appears: this CLI also works on its own. Pi
  publication requires the adapter in
  `dot_pi/private_agent/extensions/herdr-overview/README.md` and the loaded
  plugin in `dot_local/share/herdr-overview/README.md` (paths relative to the
  chezmoi source root).

## Validation

From the chezmoi source root, select the mise-managed Python for both unit
tests and the fake-backend CLI journey:

```sh
mise exec -- python3 -c 'import sys; assert sys.version_info >= (3, 11)'
PYTHONDONTWRITEBYTECODE=1 mise exec -- python3 -m unittest discover -s dot_local/share/session-recap -p 'test_*.py' -v
mise exec -- python3 tests/herdr-overview/proof.py recap
```
