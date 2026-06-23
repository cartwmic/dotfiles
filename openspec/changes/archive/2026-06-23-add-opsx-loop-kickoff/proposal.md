## Why

The `openspec-loop` skill is the loop *worker* but cannot guarantee continuation — a skill is prose read within one turn. On pi the loop is currently guaranteed only by manually running `/goal` with `PI_GOAL_JUDGE_CMD` set, or by the `opsx-loop` bash driver. There is no single in-pi command that binds worker + engine + judge, so invoking the skill alone is best-effort, not a guaranteed loop.

## What Changes

- Add a thin, self-contained pi extension `opsx-loop` registering `/opsx-loop <change>` that guarantees the loop: it injects continuation turns via `agent_end` + `sendUserMessage(followUp)` and stops only when `opsx-gate <change>` exits 0 or the iteration budget is reached.
- The judge is the deterministic `opsx-gate` command (exit 0 = met); the per-turn worker directive points at the `openspec-loop` skill.
- The budget defaults to `loop_max_iterations` read from the change's `review.md` front-matter (single budget governs the loop).
- The `goal` extension is NOT modified — it stays a generic command-judge loop. The new extension reuses the same validated `agent_end`/`followUp` mechanism (ADR-0001, ADR-0004) without coupling.

## Capabilities

### New Capabilities
- `opsx-loop-kickoff`: the `/opsx-loop` pi command that wires worker (openspec-loop skill) + engine (in-extension continuation) + judge (opsx-gate) into one guaranteed loop, with status/clear subcommands and a turn budget.

### Modified Capabilities
- (none — `goal-loop` is deliberately untouched.)

## Impact

- **Affected files:** `dot_pi/agent/extensions/opsx-loop/{index.ts, helpers.ts, helpers.test.ts}` (new extension; deployed to `~/.pi/agent/extensions/opsx-loop/` via chezmoi).
- **Deps:** none new. Reuses `opsx-gate` (already on PATH) as the judge.
- **Systems:** pi only (it is the pi adapter for the `loop-continuation` capability hook, ADR-0007). Other harnesses keep using the `opsx-loop` bash driver. Deleting this extension loses the one-command pi convenience, not the workflow.
- **Constitution:** new extension (not a skill edit) → Constitution IX adversarial review not required; reviewed at Scale M via post-impl code-review.
