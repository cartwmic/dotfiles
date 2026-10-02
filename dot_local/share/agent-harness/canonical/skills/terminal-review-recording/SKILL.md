---
name: terminal-review-recording
description: Use when asked for a watchable terminal session or demo with offline selectable-text review and MP4 playback.
---

Record the actual user path, not fake UI or accumulated screenshots.

1. Use synthetic data and owned isolated resources; keep outputs private. Read the application's isolated proof procedure. Obtain permission before touching owner sessions/devices.
2. Run `terminal-review-record --output-dir PRIVATE_NEW_DIR --size 48x32 -- COMMAND ARG...`. Input capture is disabled, but output can contain secrets. Interactive automation needs a real controlling PTY; send keys to client stdin and log actual actions separately.
3. Pace actions with real waits and hold the final frame for two seconds. Exit normally; retain failures and clean up only owned resources.
4. Keep original `record.cast`. Add optional JSON chapters (`[{"time": 2.0, "label": "Actual action"}]`) using `--export-only --chapters FILE` on the same directory. Never rewrite cast timing. Nonzero command/export status is a failure, even with playable artifacts.
5. Check metadata versions/hashes, v3 duration, exit/no-input events and full movie decode. Browser-test offline HTML with network blocked, forward/back seek, chapter navigation and current-frame selection/copy preserving row breaks, gaps and Unicode. Player 3.17.0 internal DOM extraction must be retested on upgrade; canvas-only graphics remain in cast/movie, not plain text.
6. If phone delivery is requested, verify actual target-device playback, scrub/chapters and text select/copy with the owner. Desktop emulation is not phone acceptance.
