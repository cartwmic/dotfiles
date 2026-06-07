# Execution Plan

<!-- Execution Mode = tdd-preferred: pure helpers get failing-test-first;
the agent_end loop + commands are integration-verified via `pi -p … -e`
(mechanism spike-proven in design.md Context). Same-tree; per-step commits. -->

## Plan step 1: Scaffold extension + state

- **Covers:** T1.1, T1.2
- **Pre-conditions:** none; `dot_pi/agent/extensions/web-search/index.ts` available as a reference shape.
- **Action:**
  1. Create `dot_pi/agent/extensions/goal/index.ts` with `export default function(pi)` and imports.
  2. Add `GoalState` type + closure var + env reads (`PI_GOAL_MAX_TURNS` default 25, `PI_GOAL_JUDGE_MODEL`).
  3. Commit: `feat(goal): scaffold goal-loop extension skeleton`
- **Verification:** `bun build`/typecheck the file; `pi -e <path> -p "hi" --no-session` loads without error.
- **Rollback:** delete the file.

## Plan step 2: Pure helpers (TDD)

- **Covers:** T3.3 (parseVerdict), T5.1
- **Pre-conditions:** step 1.
- **Action (5-step micro-tasks):**
  1. Write failing tests: `parseVerdict` (clean JSON / embedded JSON / garbage→met:false) citing `goal-loop.handle-evaluation-failure`; budget arithmetic citing `goal-loop.bound-the-loop-with-a-turn-budget` and `goal-loop.evaluate-each-turn-once`.
  2. Run → expect FAIL.
  3. Implement `parseVerdict` + budget helper minimally.
  4. Run → expect PASS.
  5. Commit: `feat(goal): verdict parser + budget guard with tests`
- **Verification:** unit test runner green; AC IDs present as literals in test files.
- **Rollback:** revert the commit.

## Plan step 3: Judge resolution + transcript

- **Covers:** T3.1, T3.2
- **Pre-conditions:** steps 1–2.
- **Action:**
  1. Implement `resolveJudge(ctx)` (env → preference list → `ctx.model`; first authenticating wins).
  2. Implement `extractTranscript(ctx)` (latest worker turn only, bounded — clarify A1).
  3. Commit: `feat(goal): judge model resolution and bounded transcript`
- **Verification:** `pi -p … -e` spike logging that `resolveJudge` returns an authed model and `extractTranscript` yields the last turn's text (pattern proven in design spike).
- **Rollback:** revert the commit.

## Plan step 4: Command surface

- **Covers:** T2.1, T2.2, T2.3, T2.4
- **Pre-conditions:** steps 1–3.
- **Action:**
  1. Register `/goal`; implement set / status / clear(+aliases) modes; idle→`sendUserMessage`, streaming→`followUp` (clarify C1); clear-with-no-goal no-op (clarify C2).
  2. Commit: `feat(goal): /goal set, status, and clear commands`
- **Verification:** `pi -p "/goal foo" -e …` starts a turn; `/goal` reports status; `/goal clear` removes it. Covers `goal-loop.set-a-goal`, `.check-goal-status`, `.clear-a-goal`.
- **Rollback:** revert the commit.

## Plan step 5: agent_end loop

- **Covers:** T4.1, T4.2, T4.3, T4.4, T4.5
- **Pre-conditions:** steps 1–4.
- **Action:**
  1. Register `agent_end` handler with `active && !evaluating` guard and early-return when inactive (clarify C3).
  2. Implement evaluate→branch: budget-before-inject; met wins (clarify I1); not-met→`followUp`; exhausted→clear+notify; `finally` resets `evaluating`.
  3. Wire `renderStatus` indicator; audit no captured `ctx` (D5).
  4. Commit: `feat(goal): agent_end judge loop with turn-budget guard`
- **Verification:** `-p` integration: trivially-provable condition completes (met branch); a 2-turn condition continues once then completes; a never-true condition stops at the budget. Covers `goal-loop.judge-each-completed-turn`, `.continue-when-condition-not-met`, `.complete-when-condition-met`, `.bound-the-loop-with-a-turn-budget`, `.evaluate-each-turn-once`, `.show-active-goal-indicator`.
- **Rollback:** revert the commit (loop isolated to this file).

## Plan step 6: Failure paths + deploy verify

- **Covers:** T6.1, T6.2, T6.3, T6.4
- **Pre-conditions:** steps 1–5.
- **Action:**
  1. Force no-auth judge → confirm treated not-met, no crash; confirm budget-exhaust clean stop.
  2. Manual interactive run: indicator appears/clears, loop runs while watching.
  3. `chezmoi diff`/`apply`; launch pi; confirm `/goal` discoverable.
  4. Commit: `test(goal): verify failure paths and deployment` (if any fixups).
- **Verification:** `goal-loop.handle-evaluation-failure` exercised; `chezmoi diff` clean post-apply; `/goal` in `pi` command list.
- **Rollback:** `chezmoi forget` / delete file + `chezmoi apply`.
