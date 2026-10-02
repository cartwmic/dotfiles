# Terminal review recording

`terminal-review-record --output-dir /PRIVATE/new --size 48x32 -- COMMAND ARG...`
records actual output (no input events), then produces original `record.cast`,
`render.gif`, H.264/yuv420p CFR30 `phone.mp4`, self-contained `phone.html` and
`metadata.json`. Python 3 and PATH executables asciinema 3.2.1, agg 1.9.0 and
FFmpeg >=6 with libx264/GIF decoding are required; mise pins 6.0.1. No downloads
or installs occur at runtime. Interactive callers must own a controlling PTY.

`--export-only --output-dir /PRIVATE/existing --chapters /PRIVATE/chapters.json`
exports without rewriting the v3 cast. Chapters are an array of objects with
numeric `time` in seconds and string `label`. Optional `--label` describes the
capture honestly. Output can contain secrets despite disabled input capture.
Recording requires a new private directory. Failed commands retain their exit
code; failed exports return nonzero and retain failure receipts.

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
