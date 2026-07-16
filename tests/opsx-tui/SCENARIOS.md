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
| `s07-native-retry` | `opsx-loop.interrupt-or-error-stops-the-loop`: scripted HTTP 500 then success proves Pi-native retry remains under the active loop and reaches exactly one post-success gate evaluation |
| `s08-retry-exhausted` | `opsx-loop.interrupt-or-error-stops-the-loop`: four scripted HTTP 500 responses exhaust Pi's native budget, produce one settled opsx stop, and trigger no opsx-owned retry |
| `s09-overflow-recovery` | `opsx-loop.interrupt-or-error-stops-the-loop`: settled context overflow consumes one compact-and-retry allowance and returns to normal gate flow |
| `s10-overflow-persistent` | `opsx-loop.interrupt-or-error-stops-the-loop`: second settled context overflow lands visibly without a third retry |
| `s11-clear-during-retry` | `opsx-loop.interrupt-or-error-stops-the-loop`: clear during native retry invalidates pending ownership; stale settlement cannot stop or continue the cleared loop |
| `s12-rearm-during-retry` | `opsx-loop.interrupt-or-error-stops-the-loop`: named re-arm during native retry transfers ownership only when the replacement user directive starts; old retry cannot gate the replacement |
| `s13-prequeued-rearm` | `opsx-loop.interrupt-or-error-stops-the-loop`: unrelated queued user work ahead of a re-arm stays old-owned; only the exact generated replacement directive transfers ownership and may gate the replacement |
| `s14-clear-pending-arm` | `opsx-loop.interrupt-or-error-stops-the-loop`: clear after a delayed turn-zero gate prevents the queued arm directive from reaching the provider |
| `s15-duplicate-rearm` | `opsx-loop.interrupt-or-error-stops-the-loop`: two same-change re-arms carry unique generations; stale identical prose cannot claim latest-loop ownership |
| `s16-overflow-compact-abort` | `opsx-loop.interrupt-or-error-stops-the-loop`: Escape during delayed extension-owned settled-overflow compaction lands as abort and injects no recovery turn |
| `s17-auto-compact-abort` | `opsx-loop.interrupt-or-error-stops-the-loop`: with project auto-compaction enabled, Escape during Pi-owned overflow compaction marks the pending attempt aborted so settlement cannot restart compaction |
| `s18-role-tool-lifetime` | `opsx-loop.armed-loop-mutes-generic-subagent-tool` + `opsx-loop.goal-and-conversation-kickoff`: named-to-goal replacement and failed named re-arm both restore the pre-arm tool set instead of stranding `opsx_dispatch` |
| `s19-stale-dispatch-owner` | `opsx-loop.opsx-dispatch-forces-resolved-role-model` + `opsx-loop.interrupt-or-error-stops-the-loop`: stale old request is refused before dispatch after named re-arm, while exact replacement-owned directive reaches dispatch spawn path |

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
