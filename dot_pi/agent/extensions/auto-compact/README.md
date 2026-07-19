# Auto Compact

Percent-based proactive compaction for Pi. Native auto-compaction remains disabled; this extension calls Pi's manual compaction API with its normal summary settings.

## Configuration

Edit `~/.pi/agent/extensions/auto-compact/config.json` or run `/auto-compact` in Pi:

```json
{
  "enabled": true,
  "thresholdPercent": 40,
  "checkAt": ["turn_end", "agent_end"],
  "continuation": "Continue from where you left off."
}
```

- `thresholdPercent`: context-window percentage in `(0, 100]`. Trigger comparison is inclusive.
- `checkAt`: one or both of `turn_end` and `agent_end`.
  - `turn_end` checks after every LLM/tool-loop turn.
  - `agent_end` checks once when the low-level agent run ends.
- `continuation`: follow-up text injected after **mid-turn** (`turn_end`) compaction.
  - Pi's `ctx.compact()` aborts the active agent first, so without a follow-up the run would stop.
  - Default: `"Continue from where you left off."`
  - Set to `false` (or an empty string) to disable resume.
  - `agent_end` compaction never auto-continues — the run already finished.
- `/auto-compact status`: show active configuration and file path.
- `/auto-compact reload`: reload edits made directly to the JSON file.

Config file is a chezmoi `create_` target, so later interactive edits remain machine-local and are not overwritten by `chezmoi apply`.
