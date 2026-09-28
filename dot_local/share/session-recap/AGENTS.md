# session-recap — agent instructions

## Scope and authority

This file covers `dot_local/share/session-recap/session_recap.py` and its
source-local tests. The CLI wrapper is `dot_local/bin/executable_session-recap`;
the desktop config and prompt templates are in `dot_config/session-recap/`.
The repo-root `AGENTS.md` controls chezmoi apply and secrets. This directory's
`README.md` owns human setup and CLI usage. Put Pi event handling in its
Herdr adapter; put native workspace grouping in the Herdr plugin.

## Workflow

- Run the CLI with Python 3.11+. The wrapper chooses
  `SESSION_RECAP_PYTHON`, then a compatible `python3` on `PATH`, then a mise
  shim. Test that selection if changing the wrapper; macOS's system Python
  can be too old in a Herdr-hosted shell.
- Keep recap generation a configured executable argv fed on stdin. The
  managed desktop default is `claude -p`; the host-local
  `~/.config/session-recap/config.local.toml` may override it. Tests must
  use a fake backend. Do not commit credentials or call a paid/live backend
  merely to check storage behavior.
- `create` publishes a single or group record. Pi uses `prompt set/settle`
  for the current user input, then `prepare/publish` for a settled response.
  `prompt rekey` changes only a matching current prompt under the store lock;
  it must not replace a newer input. Publication-time native membership is
  supplied by the adapter, never guessed by this store.
- Preserve dated records and the latest-success index when a command fails,
  exits nonzero, returns invalid UTF-8, or prints blank output. Failed
  attempts are visible; they cannot replace a successful recap. Keep data
  under `${XDG_DATA_HOME:-$HOME/.local/share}/session-recap/`, outside the
  chezmoi source. Check atomic writes and lock behavior in
  `test_session_recap.py` when changing the schema.
- Termux does not deploy the desktop recap command/config. Its phone-side
  passage-review library is independent.

## Validation

From the chezmoi source root, select the mise-managed Python for both the
store tests and the portable outside-in CLI proof. Check 3.11+ first; the
latter proof supplies a fake backend and needs no Pi or Herdr process.

```sh
mise exec -- python3 -c 'import sys; assert sys.version_info >= (3, 11)'
PYTHONDONTWRITEBYTECODE=1 mise exec -- python3 -m unittest discover -s dot_local/share/session-recap -p 'test_*.py' -v
mise exec -- python3 tests/herdr-overview/proof.py recap
chezmoi apply --dry-run --verbose ~/.local/bin/session-recap ~/.local/share/session-recap ~/.config/session-recap
```

Ask before a real apply or a test that uses the owner's configured recap
backend. For integration behavior, test the appropriate Pi adapter or Herdr
plugin separately; a store unit test does not prove publication in a pane.

## Completion and handoff

List source paths, command/config or schema changes, the tests and fake-backend
proof actually run, and any untested host-local backend. Say whether the
managed destinations were applied and whether local data was left untouched.
