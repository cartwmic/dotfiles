# session-recap

`session-recap` is a portable stdin-to-command recap CLI. It works without Pi or
Herdr, accepts a configured executable argv (no shell), and writes dated records
outside either application. The CLI needs Python 3.11+ (`tomllib`). Its wrapper
uses `SESSION_RECAP_PYTHON` when set, then a compatible `python3` on `PATH`, then
an available user-managed mise shim. This matters when a Herdr-hosted Pi shell
exposes macOS's older `/usr/bin/python3`. The CLI and Python implementation live
at `dot_local/bin/executable_session-recap` and
`dot_local/share/session-recap/session_recap.py` in chezmoi source.

## Configure

Desktop chezmoi profiles `personal` and `axon-work-computer` deploy the config
template and editable prompts to `~/.config/session-recap/`:

- `config.toml` — profile default command (`claude -p` for both desktop profiles)
- `single-prompt.md` — `[[LABEL]]` and `[[TEXT]]`
- `group-prompt.md` — `[[LABEL]]` and `[[MEMBERS]]`

To override only the command on one host, create the un-managed
`~/.config/session-recap/config.local.toml`:

```toml
command = ["/path/to/my-recap-command", "--stdin"]
```

The argv runs directly, not through a shell. The rendered prompt is sent on
stdin; successful nonblank UTF-8 stdout is the recap. Exit failure, invalid
UTF-8, and blank output are recorded as failed attempts and do not replace the
last successful recap. Termux does not deploy the desktop command/config; it is
an SSH client. Its phone-side review library is separate.

## Create recaps

A single input does not require a label:

```sh
printf '%s\n' 'Recent changes and the present state.' |
  session-recap create --kind single
```

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
publication.

## Checks

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s dot_local/share/session-recap -p 'test_*.py' -v
```
