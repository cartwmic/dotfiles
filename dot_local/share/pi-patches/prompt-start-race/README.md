# Prompt start race

Tested against **Pi 1.0.0** (module `dist/core/agent-session.js` and the bundled
CLI chunk that contains `AgentSession.prompt`). Enabled on `personal` and
`axon-work-computer`; other profiles (including unset) reverse only this
patch's exact blocks.

## Problem

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
- **Late start check:** after the last `await` and before the prompt consumes
  next-turn messages or calls `_runAgentPrompt`, a prompt that finds
  `_isAgentRunActive` queues into that run.

With `settlement-abort` applied, `isStreaming` also stays true while awaited
`agent_settled` handlers run after the agent loop has ended; nothing drains a
queue then. At both points a prompt that finds only that final settlement
running first waits for idle, then starts its own run (or joins one that
started meanwhile). Without `settlement-abort` this state never occurs.

Both use Pi's existing `_queueSteer` / `_queueFollowUp`, so a steer arrives at
the next turn boundary and a follow-up after the run's final reply. The loser
never enters `_runAgentPrompt`, so it cannot emit `agent_settled` or clear the
winner's state.

## Known residuals

- A queued loser has already run its `before_agent_start` handlers; custom
  messages those handlers returned are dropped. Its user text is kept.
- Any `prompt()` made while a run is active without `streamingBehavior`,
  including deliberate SDK/RPC calls, now steers instead of throwing.
- A prompt that meets final settlement waits as long as `agent_settled`
  handlers run (Esc aborts them under `settlement-abort`).

## Anchors

Exact blocks in `prompt()` only: the `if (!options?.streamingBehavior) { throw
... }` block and the `_normalizePromptImages` line (module); the matching
minified strings in the bundle chunk located by
`async prompt(text,options){if(this._isEmittingAgentSettled)`. They do not
overlap `settlement-abort` (which edits `_runAgentPrompt` and settlement) or
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
