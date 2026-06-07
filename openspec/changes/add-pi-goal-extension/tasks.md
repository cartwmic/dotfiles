## 1. Scaffold

- [x] 1.1 Create `dot_pi/agent/extensions/goal/index.ts` with the standard shape (`export default function(pi: ExtensionAPI)`), importing `ExtensionAPI` from `@mariozechner/pi-coding-agent` and `complete` from `@mariozechner/pi-ai`.
  - intent: feature
  - files_allowed:
      - "dot_pi/agent/extensions/goal/**"
  - files_forbidden:
      - "**/secrets/**"
      - "**/*.bak"
  - allow_new_files: true
- [x] 1.2 Define the in-memory `GoalState` (`condition`, `turns`, `maxTurns`, `active`, `lastReason`, `evaluating`) in the closure; read `PI_GOAL_MAX_TURNS` (default 25, D6) and `PI_GOAL_JUDGE_MODEL` env vars.
  - intent: feature
  - files_allowed:
      - "dot_pi/agent/extensions/goal/**"

## 2. Command surface (AC: set-a-goal, check-goal-status, clear-a-goal)

- [x] 2.1 Register `/goal` via `pi.registerCommand` with description + help text (condition-writing guidance: make it provable from worker output).
  - intent: feature
  - files_allowed:
      - "dot_pi/agent/extensions/goal/**"
- [x] 2.2 Set mode (`goal-loop.set-a-goal`): non-empty arg stores condition, resets turns to 0, sets active, renders indicator, starts a turn — via `sendUserMessage(condition)` when idle or `deliverAs:"followUp"` when streaming (D8 / clarify C1); replaces any existing goal.
  - intent: feature
  - files_allowed:
      - "dot_pi/agent/extensions/goal/**"
- [x] 2.3 Status mode (`goal-loop.check-goal-status`): no arg → report active condition, turns, max-turn budget, last reason; else "no active goal".
  - intent: feature
  - files_allowed:
      - "dot_pi/agent/extensions/goal/**"
- [x] 2.4 Clear mode (`goal-loop.clear-a-goal`): `clear` + aliases `stop|off|reset|none|cancel` wipe state and clear the indicator; clear with no active goal is a no-op message (clarify C2).
  - intent: feature
  - files_allowed:
      - "dot_pi/agent/extensions/goal/**"

## 3. Judge (AC: judge-each-completed-turn, handle-evaluation-failure)

- [x] 3.1 `resolveJudge(ctx)`: try `PI_GOAL_JUDGE_MODEL`, then small-model preference list, then `ctx.model`; pick first with `getApiKeyAndHeaders().ok` (D2).
  - intent: feature
  - files_allowed:
      - "dot_pi/agent/extensions/goal/**"
- [x] 3.2 `extractTranscript(ctx)`: from `ctx.sessionManager.getEntries()`, take only the latest worker turn's text blocks (+ its tool results when cheap), bounded (D7 / clarify A1).
  - intent: feature
  - files_allowed:
      - "dot_pi/agent/extensions/goal/**"
- [x] 3.3 `judge(ctx)` + `parseVerdict(text)`: `complete()` with strict system prompt demanding `{"met":boolean,"reason":string}`; tolerant parse; default `met:false` with raw text as reason on parse/auth failure (`goal-loop.handle-evaluation-failure`, D3).
  - intent: feature
  - files_allowed:
      - "dot_pi/agent/extensions/goal/**"

## 4. Loop (AC: continue/complete, bound-budget, evaluate-each-turn-once, indicator)

- [x] 4.1 Register `pi.on("agent_end")` guarded by `active && !evaluating`; return early when no goal active (clarify C3).
  - intent: feature
  - files_allowed:
      - "dot_pi/agent/extensions/goal/**"
- [x] 4.2 In-handler: set `evaluating`, increment `turns`, enforce budget BEFORE injecting (`goal-loop.bound-the-loop-with-a-turn-budget`); run `judge`; store `lastReason`; always reset `evaluating` in `finally` (`goal-loop.evaluate-each-turn-once`, D4/D6).
  - intent: feature
  - files_allowed:
      - "dot_pi/agent/extensions/goal/**"
- [x] 4.3 Branch: met → clear + indicator off + notify achieved (`goal-loop.complete-when-condition-met`; met wins over budget per clarify I1). Not-met & under budget → `sendUserMessage(reason,{deliverAs:"followUp"})` (`goal-loop.continue-when-condition-not-met`). Budget reached & not-met → clear + notify exhausted.
  - intent: feature
  - files_allowed:
      - "dot_pi/agent/extensions/goal/**"
- [x] 4.4 `renderStatus(ctx)` via `ctx.ui.setStatus("goal", …)` showing turns; cleared on clear/achieve/exhaust (`goal-loop.show-active-goal-indicator`).
  - intent: feature
  - files_allowed:
      - "dot_pi/agent/extensions/goal/**"
- [x] 4.5 Audit: confirm no `ctx` is captured across calls — only the per-handler/command `ctx` is used (D5).
  - intent: refactor
  - files_allowed:
      - "dot_pi/agent/extensions/goal/**"

## 4b. Settings (AC: configurable-judge-and-budget)

- [x] 4b.1 Add `normalizeGoalConfig` + `resolveSetting` pure helpers (env > config > default precedence) with tests citing `goal-loop.configurable-judge-and-budget`.
  - intent: feature
  - files_allowed:
      - "dot_pi/agent/extensions/goal/**"
- [x] 4b.2 Load co-located `config.json` in index.ts (relative to `import.meta.url`, tolerant of missing/invalid); apply precedence to `maxTurns` and the judge model spec (D9).
  - intent: feature
  - files_allowed:
      - "dot_pi/agent/extensions/goal/**"
- [x] 4b.3 Ship seed `create_config.json` (chezmoi `create_` — deploy once, never clobber user edits) with `judgeModel` + `maxTurns` defaults.
  - intent: feature
  - files_allowed:
      - "dot_pi/agent/extensions/goal/**"

## 4c. Interrupt handling (AC: interrupt-stops-the-loop)

- [x] 4c.1 Add `lastAssistantInfo` + `isInterruptedStop` pure helpers with tests citing `goal-loop.interrupt-stops-the-loop`.
  - intent: feature
  - files_allowed:
      - "dot_pi/agent/extensions/goal/**"
- [x] 4c.2 In `agent_end`, read `stopReason` from `event.messages`; on `aborted`/`error` clear the goal and skip re-injection (D10). Feed the same message text to the judge.
  - intent: fix
  - files_allowed:
      - "dot_pi/agent/extensions/goal/**"
- [x] 4c.3 `/goal clear` also calls `ctx.abort()` when a turn is in flight, so a running loop halts immediately.
  - intent: fix
  - files_allowed:
      - "dot_pi/agent/extensions/goal/**"

## 5. Tests (pure helpers; cite AC IDs for the verify gate)

- [x] 5.1 Unit-test `parseVerdict` (valid JSON, embedded JSON, garbage→not-met) citing `goal-loop.handle-evaluation-failure`; and budget arithmetic citing `goal-loop.bound-the-loop-with-a-turn-budget` and `goal-loop.evaluate-each-turn-once`.
  - intent: feature
  - files_allowed:
      - "dot_pi/agent/extensions/goal/**"
  - allow_new_files: true

## 6. Verify

- [x] 6.1 `-p` integration spike: cheap worker + cheap judge against a trivially-provable condition; confirm met branch, not-met continuation, and budget cutoff (`goal-loop.continue-when-condition-not-met`, `goal-loop.complete-when-condition-met`).
- [x] 6.2 Manual interactive run: footer indicator appears/clears; loop runs while watching (`goal-loop.show-active-goal-indicator`).
- [x] 6.3 Failure paths: no judge auth → treated not-met, no crash; budget exhausted → clean stop (`goal-loop.handle-evaluation-failure`).
- [x] 6.4 `chezmoi diff`/`apply` confirms deployment to `~/.pi/agent/extensions/goal/index.ts`; launch pi and confirm `/goal` is discoverable.
