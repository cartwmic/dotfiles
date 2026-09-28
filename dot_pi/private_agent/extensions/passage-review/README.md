# passage-review Pi entry point

## Overview

This desktop Pi extension registers `/review` and hands the latest assistant
reply to the standalone `passage-review` CLI. The CLI owns snapshots, comments,
and exports. The extension stores no review data.

## Setup

On a `personal` or `axon-work-computer` desktop, apply the Pi extension and the
standalone reviewer. Its setup is in
`dot_local/share/passage-review/README.md` (relative to the chezmoi source
root). Restart Pi so `/review` is registered:

```sh
chezmoi apply --dry-run --verbose ~/.pi/agent/extensions/passage-review ~/.local/bin/passage-review ~/.local/share/passage-review
chezmoi apply ~/.pi/agent/extensions/passage-review ~/.local/bin/passage-review ~/.local/share/passage-review
```

Set `PASSAGE_REVIEW_BIN` when the reviewer executable is unavailable as
`passage-review` on `PATH`. Termux installs the standalone CLI through its
phone profile and skips Pi extensions.

## Usage

When Pi is idle in interactive TUI mode, `/review` reads the latest
text-bearing assistant message from the active session branch, pauses Pi's
TUI, and pipes that reply to:

```sh
passage-review new --title "Pi reply — session SESSION_ID"
```

The CLI prints a saved review ID, opens the reply snapshot, and prompts for a
line or range and a comment in your editor. Keep the ID to reopen the review
or export selected pending notes; see `dot_local/share/passage-review/README.md`
(Usage).
Use the standalone CLI for file or stdin reviews and saved reviews while Pi or
Herdr is unavailable. `/review` does not send feedback to Pi, edit the reply,
or change pending-note state. A non-interactive Pi mode reports that this
command needs the interactive terminal.

## Troubleshooting

- `/review` is unavailable: restart Pi after applying this extension; it
  registers commands at startup.
- The command reports a missing executable: check `passage-review` on `PATH`
  or set `PASSAGE_REVIEW_BIN` to its installed path. See the standalone setup in
  `dot_local/share/passage-review/README.md`.
- No assistant reply or no interactive terminal: use the standalone CLI with
  a file or stdin snapshot. The Pi command only accepts an idle interactive
  TUI session with a text-bearing assistant reply.

## Validation

From the chezmoi source root:

```sh
node --test dot_pi/private_agent/extensions/passage-review/index.test.ts
```
