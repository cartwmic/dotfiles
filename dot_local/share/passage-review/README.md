# passage-review

`passage-review` is a standalone terminal reviewer implemented in
`dot_local/share/passage-review/passage_review.py` and launched by
`dot_local/bin/executable_passage-review`. It freezes UTF-8 input in a
user-local snapshot, stores comments separately with exact quote and 1-based
line-range anchors, and exports only pending notes selected by ID. It does not
edit source files, send feedback, or depend on Pi or Herdr. Desktop and Termux
profiles own separate local libraries; phone data is not synced back to the
desktop.

## Commands

```sh
passage-review new --file PATH
passage-review new --title TITLE < snapshot.txt
passage-review open REVIEW_ID
passage-review export REVIEW_ID --note NOTE_ID [--note NOTE_ID ...]
passage-review archive REVIEW_ID --note NOTE_ID [--note NOTE_ID ...]
passage-review delete REVIEW_ID --note NOTE_ID [--note NOTE_ID ...]
passage-review list
```

`new` saves the source before opening the reviewer. `--file` uses the file name
as the initial title and records its path as attribution. `--title` reads the
whole UTF-8 snapshot from stdin; it works with a pipe, redirected file, or a
terminal selection pasted into the terminal and ended with Ctrl-D. Once open,
page through the frozen source, enter a line or line range, and write the
comment in `$VISUAL`, falling back to `$EDITOR` and then `vi`. Use your phone's
existing dictation keyboard in that editor if desired. Blank comments are not
saved. Reopening an ID shows the same bytes and lets you add more comments.

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
  snapshot.txt      # read-only frozen UTF-8 source
  notes/<note-id>.json
  notes/archived/<note-id>.json
  exports/<timestamp>-<id>.md
```

Review and note JSON are schema version 1. Snapshot hashes are checked before
opening, commenting, or exporting; a changed snapshot fails closed. Files are
created user-private. The library is local data and is not automatically
synced. Set `XDG_DATA_HOME` before invoking the command to use another local
library root.

## Pi entry point

The optional Pi `/review` command passes the latest assistant text to
`passage-review new --title ...` on stdin. It pauses the Pi TUI while the
standalone command runs. The extension only provides this source entry point;
the CLI owns snapshots, notes, state, and export.

## Checks

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s dot_local/share/passage-review -p 'test_*.py' -v
```
