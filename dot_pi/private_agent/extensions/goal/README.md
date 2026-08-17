# Goal loop

A Claude-Code-style `/goal` for Pi: set a completion condition, keep the worker turning until a **separate** judge says the condition is met, and stop on success, interrupt, unresolved error, or a hard turn budget.

This is a generic loop runtime with a pluggable judge. It is not an OpenSpec or `opsx` runner. Do not couple it to that retired workflow.

Authoring layout for this folder lives in the parent extensions README (`dot_pi/agent/extensions/README.md`).

## Overview

The worker (the session model) does the work. A configurable judge — a different model, or an optional shell command — decides whether the latest completed attempt satisfies the goal. Not met → inject the reason as a follow-up and start another turn. Met → clear and notify. The budget guarantees termination.

Evaluate completion on **`agent_end` / `agent_settled` boundaries**, not `turn_end`. `turn_end` is mid-run: it fires per internal LLM turn, including retries and continuations. Goal evaluation waits until a low-level attempt finishes (`agent_end`) and treats an error as terminal only after Pi has settled (`agent_settled`).

Implementation: [index.ts](./index.ts) (runtime) and [helpers.ts](./helpers.ts) (pure policy). Tests: [helpers.test.ts](./helpers.test.ts).

## Setup

This directory is the chezmoi **source**. It deploys to `~/.pi/agent/extensions/goal`. Confirm the source is present:

```sh
cd ~/.local/share/chezmoi/dot_pi/agent/extensions/goal && ls -1
```

You should see [index.ts](./index.ts), [helpers.ts](./helpers.ts), [helpers.test.ts](./helpers.test.ts), and [create_config.json](./create_config.json). After apply, restart Pi so it reloads extensions. Apply itself is the parent-tree procedure in `dot_pi/agent/extensions/README.md`; do not apply from here.

`[create_config.json](./create_config.json)` is a chezmoi `create_` source. Chezmoi writes the destination `config.json` only when that dest file does not already exist. After the first apply, interactive edits to `~/.pi/agent/extensions/goal/config.json` stay machine-local and are not overwritten by later `chezmoi apply`.

Default create contents:

```json
{
  "judgeModel": "anthropic/claude-haiku-4-5",
  "maxTurns": 25
}
```

Optional `judgeCommand` is also accepted in that file (see Usage).

## Usage

### Commands

| Command | Effect |
| --- | --- |
| `/goal <condition>` | Replace any active goal, start working immediately (follow-up). |
| `/goal` or `/goal status` or `/goal ?` | Show condition, `turns/maxTurns`, and last verdict. |
| `/goal clear` | Stop and clear. Aliases (exact, case-insensitive): `stop`, `off`, `reset`, `none`, `cancel`. Also aborts an in-flight turn. |

A condition that merely **contains** a keyword (for example `stop the flaky tests`) is still a set. Matching is exact on the trimmed argument.

### Loop boundaries

1. `/goal <condition>` records serializable state (`condition`, `turns`, `maxTurns`) and sends a follow-up: work until the condition is met, and state how the output proves it.
2. On **`agent_end`** (a low-level attempt boundary):
   - Inactive or already evaluating → no-op (re-entrancy guard).
   - `stopReason=aborted` and auto-compact announced a resume (`auto-compact:will-resume-interrupted-run` from `dot_pi/agent/extensions/auto-compact/events.ts`) → **preserve** the goal; the follow-up after compaction is a new run. See `dot_pi/agent/extensions/auto-compact/README.md`.
   - Other `aborted` (user interrupt) → **stop immediately**. Never wait for settlement.
   - `stopReason=error` → **defer**. Set `pendingError` and wait. Pi may still retry, compact, or continue the same user-visible turn.
   - Otherwise → **evaluate** once: increment `turns`, run the judge against the attempt’s assistant text (session transcript fallback).
3. On **`turn_start`**, if a deferred error is still latched, clear it. A new turn starting after an errored attempt means Pi continued the run; do not kill a healthy loop later at settlement. `turn_start` is **not** an evaluation point.
4. On **`agent_settled`**, if `pendingError` is still set, the session is idle, and nothing else started a new run: **stop** the loop as an unresolved error.

After a clean evaluation:

- **Met** → clear, notify achieved. Met wins even when the budget is reached on the same turn.
- **Not met and budget exhausted** (`turns >= maxTurns`) → clear, notify stopped.
- **Not met under budget** → follow-up `[goal not yet met] <reason>` and keep working.

`turns` counts evaluated attempts, including the first set turn. Default budget is 25.

### Judge (not the worker)

The judge is separate from the session/worker model. Precedence for every setting: **env var > `config.json` > built-in default**. Empty env values are ignored.

| Setting | Env | Config key | Default |
| --- | --- | --- | --- |
| Turn budget | `PI_GOAL_MAX_TURNS` | `maxTurns` | `25` |
| Model judge | `PI_GOAL_JUDGE_MODEL` | `judgeModel` | Preference list, then the session model |
| Command judge | `PI_GOAL_JUDGE_CMD` | `judgeCommand` | none |

`PI_GOAL_JUDGE_MODEL` / `judgeModel` is `provider/model-id` (for example `anthropic/claude-haiku-4-5`). When unset, the runtime tries `anthropic/claude-haiku-4-5`, then `deepseek/deepseek-v4-flash`, then the current session model, using the first authenticated candidate.

When `PI_GOAL_JUDGE_CMD` or `judgeCommand` is set, that **command judge replaces the model judge**. Exit `0` = met; non-zero or spawn failure = not met, with combined stdout/stderr as the reason. The command may inspect filesystem and git state outside the transcript. `GOAL_CONDITION` is exported to it.

The model judge asks for a structured `submit_verdict` tool call (`met` + one-sentence `reason`). If the model emits text instead, the runtime parses the first JSON object; garbage defaults to not-met. Judge failures never crash the turn: they count as not-met with an evaluator-error reason.

Custom-api providers registered through Pi (for example claude-bridge) are routed through that provider’s `streamSimple`, not bare `pi-ai` `complete()`.

### Never capture `ctx`

Hold the `pi` API object plus serializable goal state only. Every handler and event callback must use the `ctx` argument for that call. Do **not** stash `ExtensionContext` from `session_start` (or any other hook) in a long-lived closure.

A captured `ctx` is stale after `newSession`, `fork`, `switchSession`, `reload`, or teardown. Accessing it throws: `This extension ctx is stale after session replacement or reload.`

### Debug

`PI_GOAL_DEBUG` selects the debug log path (default `~/.pi/goal-debug.log`). Set `0` / `off` / `false` to disable. Rotates at 5MB, keeping one `.1` generation.

## Validation

From **this directory** (relative imports match runtime):

```sh
node --test helpers.test.ts
```

That is the in-tree convention from `dot_pi/agent/extensions/README.md`. Today [helpers.test.ts](./helpers.test.ts) still imports `bun:test`, so this Node command fails to load the suite until the tests move to `node:test`. Until then the same file runs with:

```sh
bun test helpers.test.ts
```

Do not treat a passing helper suite as proof of the `agent_end` / `agent_settled` wiring in [index.ts](./index.ts); those paths are integration behavior around the pure helpers.
