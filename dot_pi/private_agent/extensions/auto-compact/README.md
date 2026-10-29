# Auto Compact

Percent-based proactive compaction for Pi. Native auto-compaction remains disabled; this extension calls Pi's manual compaction API with its normal summary settings.

## Configuration

Edit `~/.pi/agent/extensions/auto-compact/config.json` or run `/auto-compact` in Pi:

```json
{
  "enabled": true,
  "thresholdPercent": 40,
  "thresholdTokens": 200000,
  "checkAt": ["turn_end", "agent_end"],
  "continuation": "Continue from where you left off."
}
```

- `thresholdPercent`: context-window percentage in `(0, 100]`. Trigger comparison is inclusive.
- `thresholdTokens` (default 200000): absolute cap. Compaction fires at whichever comes first, `thresholdPercent` of the model's window or this many tokens. A 1M-window model compacts at 200k (not 400k); a 272k-window model still compacts at 40%, about 109k. The default lives in code, so an existing `config.json` without this key picks it up on reload.
- `checkAt`: one or both of `turn_end` and `agent_end`.
  - `turn_end` checks are deferred until the next lifecycle event: another `turn_start` resumes after compaction; a final `agent_end` compacts without resuming.
  - `agent_end` is the configured final-run checkpoint; its check runs at
    `agent_settled`, after Pi exhausts retries and queued continuations.
- `continuation`: follow-up text injected after **inter-turn** (`turn_end`) compaction.
  - Pi's `ctx.compact()` aborts the active agent first, so without a follow-up the run would stop.
  - Before a resumed abort, auto-compact emits
    `auto-compact:will-resume-interrupted-run` on Pi's extension event bus. goal
    preserves its active loop.
  - Default: `"Continue from where you left off."`
  - Set to `false` (or an empty string) to disable resume.
  - Final-turn and `agent_end` compactions never auto-continue — the run already finished.
  - A message you send (Enter or Alt+Enter) while auto-compaction runs replaces the
    continuation, whether compaction succeeds or fails. Pi submits that queued
    message after compaction, and the extension sees it through Pi's `input`
    event before its completion callback. Extension slash-commands and
    extension-sent messages do not cancel it.
- Pause markers: before `ctx.compact()` aborts the run, the extension writes an `auto-compact` session entry `{kind: "compacting", resume}` (`resume`: a continuation will follow). When compaction ends it writes `{kind: "compacted", resumeSent}`, or `{kind: "compaction_failed", resumeSent, error}` on failure or session shutdown, before any continuation. `resumeSent: true` means the continuation was submitted to Pi; Pi can still reject it later, so a reader should also check that the worker started again. `resumeSent: false` means no continuation was sent: none was due, or a message typed during compaction replaced it. If submitting throws (a stale runtime), or a message typed during compaction reaches Pi after the continuation was submitted and replaces it, a second closing marker with `resumeSent: false` follows; readers take the last one. Programs that watch session files (the coordinator daemon) read these to tell a compaction pause from a real abort.
- `maxIneffectiveCompactions` (default 2): circuit breaker. After this many consecutive compactions that fail or do not bring context below the threshold, auto-compaction pauses.
- `breakerCooldownSeconds` (default 300): a tripped breaker retries **once** after this wait instead of staying paused for the session. Each consecutive trip doubles the wait (capped at 3600s); a reading below the threshold resets it. `0` restores the old behavior: stay paused until `/auto-compact reload` or a new session.
- Visibility: a failed compaction, a breaker pause and a breaker retry are each written as a JSON line to `auto-compact.log` beside the extension, as an `auto-compact` custom entry in the session file (not sent to the model; this is what a headless session shows), and as a warning in the TUI.
- `/auto-compact status`: show active configuration, file path, and whether the breaker is paused (with the retry time).
- `/auto-compact reload`: reload edits made directly to the JSON file.

Summary size cap: even with native auto-compaction off, Pi limits the history summary to min(0.8 x `compaction.reserveTokens`,
model max output) (0.5 x for a split-turn prefix). The chezmoi-managed Pi settings set `reserveTokens` to 100000. At Pi's 16384
default the history cap is 13107 tokens, which a long session's iterative summary can reach; the compaction then fails with
"generation hit the token cap", and after `maxIneffectiveCompactions` failed attempts this extension pauses (see `breakerCooldownSeconds`: it retries once after a cooldown, or stays paused for the session when that is 0).

Config file is a chezmoi `create_` target, so later interactive edits remain machine-local and are not overwritten by `chezmoi apply`.
