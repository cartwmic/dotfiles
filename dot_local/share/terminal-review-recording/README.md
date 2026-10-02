# Terminal review recording

`terminal-review-record --output-dir /PRIVATE/new --size 48x32 -- COMMAND ARG...`
records actual output (no input events), then produces original `record.cast`,
`render.gif`, H.264/yuv420p CFR30 `phone.mp4`, self-contained `phone.html` and
`metadata.json`. Python 3 and PATH executables asciinema 3.2.1, agg 1.9.0 and
FFmpeg >=6 with libx264/GIF decoding are required; mise pins 6.0.1. No downloads
or installs occur at runtime. Interactive callers must own a controlling PTY. Key/typed-text overlays additionally require FFmpeg's `drawtext` filter and an available monospace font.

`--export-only --output-dir /PRIVATE/existing --chapters /PRIVATE/chapters.json`
exports without rewriting the v3 cast. Chapters are an array of objects with
numeric `time` in seconds and string `label`. Optional `--label` describes the
capture honestly. Output can contain secrets despite disabled input capture.
Recording requires a new private directory. Failed commands retain their exit
code; failed exports return nonzero and retain failure receipts.

## Explicit input overlays

Supply `--actions /PRIVATE/actions.json` on capture or export-only. This is an
explicit safe action log written by the demo driver when it actually sends input,
not automatic keylogging. Record every key and typed prompt, including Enter,
Escape and shortcuts. Times are seconds on the original cast timeline; synchronize
the driver clock to recorded output, not launcher startup. Keep real passwords,
tokens and confidential prompts out of the log. Do not reconstruct actions from
screen text or invent keystrokes for externally triggered operations.

```json
[
  {"time": 2.0, "kind": "text", "value": "/latency inspect"},
  {"time": 2.1, "kind": "key", "value": "Enter"},
  {"time": 4.0, "kind": "key", "value": "Escape"}
]
```

The MP4 reserves a labeled input band below the terminal, so annotations never
cover application output. The offline HTML shows the same timed annotations
below the player, including on pause, chapter jumps and backward seeks.
Every input stays visible for three seconds; overlapping inputs are shown together, not silently discarded. Typed text is shown
literally; it is not an FFmpeg expression or HTML markup. Current-frame
selection/copy remains application text; input annotations are separately
selectable. Original `record.cast` and raw `render.gif` are not annotated or retimed.

Logs are bounded to 256 entries and 512 KiB, with values up to 2,048 characters.
Times must be finite, ordered and within the cast. ANSI/control sequences are
rejected; use human-readable key names. If wrapping would exceed 16 input-band
lines, export refuses: send and record actual smaller typing chunks instead.
Saved `actions.json` is retained and used by subsequent chapter-only reexports.
Metadata binds the supplied action log and declares the annotation dimensions.
Export keeps the original duration; input annotations near immediate client exit
can otherwise be unreadably short. Keep the **recorded command** alive for three
real seconds after the final input/client exit, preserving its status. For example:

```sh
terminal-review-record --output-dir /PRIVATE/new --actions /PRIVATE/actions.json -- \
  sh -c '"$@"; status=$?; sleep 3; exit "$status"' sh COMMAND ARG...
```

Verify the final action's actual movie dwell, not just a paused HTML frame.
Do not append synthetic cast events or retime the original recording.
Privacy depends on the caller's explicitly logged values; the utility does not
claim to recognize every secret. No raw input events are enabled.

Cast intervals are archival timing. GIF/MP4 are quantized; only renderer-added
tail beyond original cast duration is trimmed. Metadata records actual binary
versions/hashes, artifact hashes and durations; full decode is checked.

The offline page uses vendored player 3.17.0 (Apache-2.0; `assets/LICENSE` and
`provenance.json`). Current-frame text extracts the pinned player's rendered
DOM cell positions, preserving row breaks/gaps/CJK/combining text. Canvas-only
block graphics are not reconstructed. Retest DOM extraction on upgrades.
Pause/seek before selecting or copying. Physical phone validation is separate.

Source wrapper works directly from this worktree. Tests are source-only under
`tests/terminal-review-recording`; private outputs/dependencies never belong in
Git. Deploy only after targeted chezmoi preview/approval; canonical skill sync
is a separate worktree-source preview/approval. No service or viewer install.

Outside-in proof (use an owned private directory; no global installs):

```sh
python3 tests/terminal-review-recording/proof.py --output /PRIVATE/proof
NODE_PATH=/PRIVATE/deps/node_modules CHROMIUM=/PATH/to/chromium \
  node tests/terminal-review-recording/browser.cjs /PRIVATE/prep \
  /PRIVATE/chapters.json /PRIVATE/original/phone.html
```

The browser comparison expects `proof/fixture`, `resize`, and `primary` exports
in the prep directory. `resize` is a real PTY resize fixture; `primary` is a
separate export of the unchanged original cast, not a new native recording.
