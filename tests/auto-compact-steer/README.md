# auto-compact steer proof

Black-box proof for the auto-compact continuation rule and the
`prompt-start-race` pi-patch. It drives Pi's real TUI in a PTY with real keys
(Enter, Alt+Enter, Esc) against a local scripted OpenAI-compatible backend. No
credentials, no paid model calls, no writes to the installed Pi or live `~/.pi`
in private mode.

## Run

```sh
python3 tests/auto-compact-steer/proof.py            # private copies: AC-1..AC-7, AC-9 + negative controls
python3 tests/auto-compact-steer/proof.py --prepare-package /tmp/auto-compact-steer-prepared/pi-coding-agent
env PI_SETTLEMENT_SOURCE_PACKAGE=/tmp/auto-compact-steer-prepared/pi-coding-agent python3 tests/pi-patches/settlement_abort.py
python3 tests/auto-compact-steer/proof.py --installed --journeys AC-1,AC-4   # after an approved live apply
```

Requires Pi 1.0.0 at the mise path (override with
`PI_AUTO_COMPACT_STEER_SOURCE_PACKAGE`), Node, git, and the Python module
`pyte` (terminal emulator for screen assertions). Set
`PI_AUTO_COMPACT_STEER_ARTIFACTS=/abs/dir` to keep each journey's trace, backend
requests, final screen and raw output.

## What each journey asserts

Each journey runs Pi with an isolated `HOME`/agent dir, a 8192-token proof
model, native compaction off, and `fixture.mjs` (writes a JSONL trace of
`input`, `before_agent_start` and `agent_settled`; optionally races two prompts
with file-released holds). Everything fails closed on timeout.

- **Negative controls:** the baseline extension (pre-fix commit
  `BASELINE_REF` in `proof.py`) on unpatched Pi
  shows the prompt-start error or sends the continuation; the baseline
  extension on patched Pi still sends the continuation; the race on unpatched
  Pi shows an error or a false `agent_settled`.
- **AC-1 / AC-2:** a warm-up turn, then a tool-call turn over the 50% threshold
  triggers auto-compact; the summary request is held while the message is typed
  (Enter / Alt+Enter); after release the backend gets that message next, its
  reply renders, no "Failed to send queued message", no pending
  `Steering:`/`Follow-up:` line, and the continuation never reaches the backend,
  session file or screen.
- **AC-3:** same with nothing typed; the continuation is sent and answered.
- **AC-4:** the queued message's reply is held mid-stream; Esc makes the backend
  see the stream cancelled, the working indicator clears, and a new prompt
  completes.
- **AC-5:** the summary request fails (HTTP 500) with a message queued; that
  message is sent next and the continuation is not.
- **AC-6 / AC-9:** a TUI prompt and an extension prompt start together, under a
  late schedule (both held in `before_agent_start`, past the early check) and an
  early schedule (loser held in its input handler). The winner's first reply is
  a tool call held until the loser shows as queued. A steer/default loser must
  appear in the request after the tool result, before the final reply, then Esc
  cancels that held stream; a follow-up loser must appear only after the final
  reply. No error on screen, and exactly one `agent_settled` for the run.
- **AC-7:** on a private copy, the normal apply helper over a private patch root
  applies the patch; `--check` passes; re-apply is a no-op; no receipts; all
  siblings `--check`; a disabled profile reverses exactly; missing/ambiguous
  anchors refuse without writes; applying before or after `settlement-abort`
  gives identical files.

`--prepare-package` writes a copy of the installed Pi with `settlement-abort`
reversed and `prompt-start-race` applied (other installed siblings unchanged),
for the settlement-abort coexistence run.
