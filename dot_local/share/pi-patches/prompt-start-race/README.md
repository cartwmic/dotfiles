# Prompt start race

> **Layout:** `patch.mjs` selects `patch.pi-1.1.mjs`, `patch.pi-1.2.mjs` or `patch.pi-1.3.mjs` by installed Pi version (see ../README.md, "Pi version selection"). This README and its proofs describe the Pi 1.2.x payload (`patch.pi-1.2.mjs`); `patch.pi-1.3.mjs` is a byte-identical copy whose anchors all match Pi 1.3.0; the 1.1.x payload is the unchanged pre-port revision.


Tested against **Pi 1.2.0** (module `dist/core/agent-session.js` and the bundled
CLI chunk that contains `AgentSession.prompt`). Enabled on `personal` and
`axon-work-computer`; other profiles (including unset) reverse only this
patch's exact blocks.

## Pi 1.2.0 changes

Upstream PR #10739 replaced `_runAgentPrompt` with `_startRun`, which sets
`_isAgentRunActive` synchronously before `before_agent_start`. The old "late"
window (two prompts both held in `before_agent_start`, past the early check) can
no longer occur: the second prompt sees the run and meets the early branch. That
part of the problem is fixed upstream, so the old post-`_normalizePromptImages`
anchor and the late test schedule are gone. The early branch is still needed
(an idle TUI submit without `streamingBehavior` still throws), and a narrow
window remains while `prompt()` awaits `checkAuth` just before `_startRun`, so
the late check moved to just before `await this._startRun({ messageType: "user"`.

## Problem (as of Pi 1.0.0; see above for 1.2.0)

`AgentSession.prompt()` checks whether a run is active, then awaits input
handlers, auth, `before_agent_start` and image normalization before it starts
the run. Two prompts that start together can both pass the first check. The
second one to reach the run either throws `Agent is already processing a
prompt` from pi-agent-core, after entering `_runAgentPrompt`, so its cleanup
emits `agent_settled` and clears `_isAgentRunActive` while the winning run
still streams. Escape then does nothing until that run ends. Or, when the
winner started during the loser's input handlers, the loser meets the streaming
branch and throws `Specify streamingBehavior` because the idle TUI submits
without one. Either way the message is lost.

The common trigger was the auto-compact extension's continuation racing the
TUI's flush of messages queued during compaction.

## What the patch does

Both places where `prompt()` can discover an active run now queue instead of
failing:

- **Early streaming branch:** a prompt without `streamingBehavior` queues as a
  steer instead of throwing.
- **Late start check:** after the last `await` (auth check) and before
  `_startRun`, a prompt that finds `_isAgentRunActive` queues into that run.

With `settlement-abort` applied, `isStreaming` also stays true while awaited
`agent_settled` handlers run after the agent loop has ended; nothing drains a
queue then. At both points a prompt that finds only that final settlement
running first waits for idle, then starts its own run (or joins one that
started meanwhile). Without `settlement-abort` this state never occurs.

Both use Pi's existing `_queueSteer` / `_queueFollowUp`, so a steer arrives at
the next turn boundary and a follow-up after the run's final reply. The loser
never enters `_startRun`, so it cannot emit `agent_settled` or clear the
winner's state.

## Known residuals

- The late check (auth-await window) is not exercised by the proof: 1.2.0 gives
  no deterministic way to pause there. It is syntax-checked and mirrors the
  early branch.
- The settlement wait applies only with `settlement-abort` (not yet verified on
  1.2.0); `settling` proof journeys are blocked until that patch is ported.

- A queued loser has already run its `before_agent_start` handlers; custom
  messages those handlers returned are dropped. Its user text is kept.
- Any `prompt()` made while a run is active without `streamingBehavior`,
  including deliberate SDK/RPC calls, now steers instead of throwing.
- A prompt that meets final settlement waits as long as `agent_settled`
  handlers run (Esc aborts them under `settlement-abort`).

## Anchors

Exact blocks in `prompt()` only: the `processedInput` destructuring line, the
`if (!options?.streamingBehavior) { throw ... }` block and the
`await this._startRun({ messageType: "user", ... })` line (module); the matching
minified strings in the bundle chunk located by
`async prompt(text,options){if(this._isEmittingAgentSettled)`. They do not
overlap `settlement-abort` (which edits settlement) or
`standing-reminder-origin` (which edits the queue calls' `source` argument).
Changed, ambiguous, partial or mixed application refuses before writing;
rewritten JavaScript is syntax-checked in temporary files first.

## Validation

```sh
python3 tests/auto-compact-steer/proof.py
```

For a private target only (suppresses the state receipt):

```sh
PI_PROMPT_START_RACE_PACKAGE=/absolute/private/pi-copy \
PI_CHEZMOI_PROFILE=personal node dot_local/share/pi-patches/prompt-start-race/patch.mjs
PI_PROMPT_START_RACE_PACKAGE=/absolute/private/pi-copy \
PI_CHEZMOI_PROFILE=personal node dot_local/share/pi-patches/prompt-start-race/patch.mjs --check
```

After a same-version Pi reinstall, rerun the apply helper and `--check`: the
onchange hash does not detect replaced `dist/` contents.
