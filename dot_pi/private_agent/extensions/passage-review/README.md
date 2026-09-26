# passage-review Pi entry point

Registers `/review`. When Pi is idle in interactive TUI mode, it reads the
latest text-bearing assistant message from the active session branch, pauses
Pi's TUI, and pipes that reply to:

```sh
passage-review new --title "Pi reply — session SESSION_ID"
```

Set `PASSAGE_REVIEW_BIN` if the standalone executable is not named
`passage-review` on `PATH`. The extension provides only a source entry point:
it does not create snapshots, store comments, change note state, or export
feedback. Use the standalone CLI for file/stdin reviews and saved reviews even
when Pi or Herdr is unavailable. `/review` does not send text back to Pi.
