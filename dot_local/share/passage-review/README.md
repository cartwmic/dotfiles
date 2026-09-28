# passage-review

## Overview

`passage-review` is a standalone terminal reviewer implemented in
`dot_local/share/passage-review/passage_review.py` and launched by
`dot_local/bin/executable_passage-review`. It freezes UTF-8 input in a
user-local snapshot, stores comments separately with exact quote and 1-based
line-range anchors, and exports only pending notes selected by ID. It does not
edit source files, send feedback, or depend on Pi or Herdr. Desktop and Termux
profiles own separate local libraries; phone data is not synced back to the
desktop.

## Setup

Use the chezmoi profile for this machine. Desktop profiles install the CLI
under `~/.local/bin`; Termux installs a phone-owned wrapper under `~/bin`:

```sh
# Desktop
chezmoi apply --dry-run --verbose ~/.local/bin/passage-review ~/.local/share/passage-review
chezmoi apply ~/.local/bin/passage-review ~/.local/share/passage-review
# Termux
chezmoi apply --dry-run --verbose ~/bin/passage-review ~/.local/share/passage-review
chezmoi apply ~/bin/passage-review ~/.local/share/passage-review
```

The wrapper needs `python3` on `PATH` and a terminal editor (`$VISUAL`,
`$EDITOR`, or `vi`). Termux's phone bootstrap installs `vim`; its library
stays on the phone. Use an interactive terminal with `/dev/tty` to add notes.

## Usage

```sh
passage-review new --file PATH
passage-review new --title TITLE < snapshot.txt
passage-review open REVIEW_ID
passage-review export REVIEW_ID --note NOTE_ID [--note NOTE_ID ...]
passage-review archive REVIEW_ID --note NOTE_ID [--note NOTE_ID ...]
passage-review delete REVIEW_ID --note NOTE_ID [--note NOTE_ID ...]
passage-review list
```

`new` prints `Saved immutable review snapshot REVIEW_ID`, then opens the
reviewer. Keep that ID for `open` and `export`. `--file` uses the file name
as the initial title and records its path as attribution. `--title` reads the
whole UTF-8 snapshot from stdin; it works with a pipe, redirected file, or a
terminal selection pasted into the terminal and ended with Ctrl-D. Once open, page through the frozen source, choose `[a]dd`, enter a line or
line range, and write the comment in `$VISUAL`, falling back to `$EDITOR` and
then `vi`. The CLI prints `Saved pending note NOTE_ID`; use that ID with
`passage-review export REVIEW_ID --note NOTE_ID` after quitting the reviewer.
Use your phone's existing dictation keyboard in that editor if desired. Blank
comments are not saved. Reopening an ID shows the same bytes and lets you add
more comments.

Each comment has its own ID. `export` accepts repeated `--note` flags, includes
only those pending notes, quotes and attributes each exact passage, and saves a
Markdown copy under the review's `exports/` directory. It also displays the
result. A supported local clipboard command is used when available; over SSH,
the CLI requests the viewing terminal clipboard with OSC 52. If the terminal
does not support it, the displayed and saved file remains available. Export
never archives or deletes notes. Use `archive` or `delete` explicitly to
change pending-note state.

For a terminal selection already copied to the clipboard:

```sh
# macOS
pbpaste | passage-review new --title "Terminal selection"
# Termux
termux-clipboard-get | passage-review new --title "Terminal selection"
```

No Herdr adapter is required. If a Herdr pane-capture adapter is used, keep it
as a source-only entry point and pipe its captured text to
`passage-review new --title "Pane output"`. The CLI and saved-review commands
have no Herdr/Pi imports or process requirement. On a phone where direct remote
selection capture is unavailable, open the saved snapshot and select recent
output by its displayed line range.

## Local library

By default the library is `${XDG_DATA_HOME:-$HOME/.local/share}/passage-review/`:

```text
reviews/<review-id>/
  review.json       # title, source attribution, timestamp, snapshot SHA-256
  snapshot.txt      # hash-checked frozen UTF-8 source
  notes/<note-id>.json
  notes/archived/<note-id>.json
  exports/<timestamp>-<id>.md
```

Review and note JSON are schema version 1. The CLI commands are the supported
interface. These JSON files are local storage. Do not build integrations
against their layout. Snapshot hashes are checked before opening, commenting, or exporting; a
changed snapshot fails closed. Files are created user-private. The library is
local data and is not automatically synced. Set `XDG_DATA_HOME` before
invoking the command to use another local library root.

## Pi entry point

The optional Pi `/review` entry point in
`dot_pi/private_agent/extensions/passage-review/README.md` (relative to the
chezmoi source root) passes the latest assistant text to
`passage-review new --title ...` on stdin. It pauses the Pi TUI while the
standalone command runs. The extension only provides this source entry point;
the CLI owns snapshots, notes, state, and export.

## Troubleshooting

- `passage-review` is missing: check the profile-specific wrapper path under
  `~/.local/bin` on desktop or `~/bin` on Termux, and that its directory is on
  `PATH`. The wrapper also needs `python3` on `PATH`.
- The review prints a snapshot but offers no `[a]dd` prompt: there is no
  controlling `/dev/tty`. Reopen the saved ID from an interactive terminal.
  The snapshot remains readable without a TTY; note creation needs one.
- Clipboard transfer fails: `export` still prints the feedback and saves a
  Markdown copy in the review's `exports/` directory.

## Validation

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s dot_local/share/passage-review -p 'test_*.py' -v
```
