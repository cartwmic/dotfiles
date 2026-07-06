# opsx-loop TUI scenarios

This suite validates `/opsx-loop` through a real Pi TUI driven by tmux.
It is intentionally separate from helper/unit tests because command handlers can
return values that Pi discards; only pane-visible checks catch that user-facing
failure mode.

Default scenarios use:

- a private tmux server per scenario (`tmux -L ...`)
- `pi --no-session -ne` with the source `dot_pi/agent/extensions/opsx-loop`
- a fake `opsx` executable prepended to `PATH`
- a fake OpenAI-compatible provider registered as `opsx-tui-fake/smoke`
- temp repos under `${TMPDIR}`

No default scenario needs hosted model credentials.

## Scenarios

| Scenario | Coverage |
|---|---|
| `s00-status-clear` | `opsx-loop.tui-scenarios-exercise-user-visible-slash-commands`: bare/status/clear pane-visible notifications |
| `s01-models` | `opsx-loop.tui-scenarios-exercise-user-visible-slash-commands`: `models` output visibility and full argv preservation |
| `s02-green-change` | `opsx-loop.tui-scenarios-exercise-deterministic-loop-states`: green gate reports ready and does not inject worker turn |
| `s03-red-arm-clear` | `opsx-loop.tui-scenarios-exercise-deterministic-loop-states`: red gate arms, status reports active change, clear stops |
| `s04-goal-distill` | `opsx-loop.tui-scenarios-exercise-deterministic-loop-states`: multi-word goal reaches distill directive; new intent pauses for confirmation |
| `s05-hold-rearm` | `opsx-loop.tui-scenarios-exercise-deterministic-loop-states`: `loop_hold` stops continuation and named re-arm clears it |
| `s06-interrupt-optional` | Optional interrupt smoke; skipped unless `OPSX_TUI_ENABLE_INTERRUPT=1` |

## Running

```bash
bash tests/opsx-tui/scripts/run-all-scenarios.sh
```

Useful filters:

```bash
OPSX_TUI_SCENARIO_FILTER='s00|s01' bash tests/opsx-tui/scripts/run-all-scenarios.sh
OPSX_TUI_ENABLE_INTERRUPT=1 OPSX_TUI_SCENARIO_FILTER=s06 bash tests/opsx-tui/scripts/run-all-scenarios.sh
```

## Optional real-model smoke

A real provider smoke test is intentionally not part of the default runner. If a
future scenario is added, it must stay opt-in via an environment flag and must
document required credentials, expected latency, and cost/flake trade-offs.

## Failure artifacts

Runner output lands under `tests/opsx-tui/.test-output/`:

- `SUMMARY.md`
- `<scenario>.run.log`
- `<scenario>.pane.log`
- `<scenario>.provider.log`

Set `KEEP_OPSX_TUI_TMP=1` to preserve temp repos and fake command logs for
manual debugging.
