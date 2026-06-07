# Verify

**Generated:** 2026-06-07 · **Base SHA:** ce6ba628 · **Verification Mode:** retained-recommended

## Check 1 — Structural validation
`openspec validate add-pi-goal-extension --strict` → **PASS** ("is valid").

## Check 2 — Task completion
`grep -c '^- \[ \]' tasks.md` → **0** unchecked. **PASS**.

## Check 3 — Delta vs current-spec coherence
New capability `goal-loop`; delta is ADDED-only (no existing `openspec/specs/goal-loop/` to conflict with). Parseable. **PASS**.

## Check 4 — Commit hygiene
| Commit | Subject len | Body explains why |
|---|---|---|
| feat(goal): goal-loop pi extension (Claude-Code-style /goal) | 60 | yes |
| docs(opsx): add-pi-goal-extension change artifacts | 50 | yes |
Both ≤72. **PASS**.

## Check 5 — AC ↔ test mapping (canonical IDs)
- **Forward:** all 12 `goal-loop.*` AC IDs (incl. `configurable-judge-and-budget`, `interrupt-stops-the-loop`) appear in committed files. **PASS**.
- **Reverse:** `helpers.test.ts` cites 7 canonical AC IDs as string literals. ≥1 match. **PASS**.

## Check 6 — Constitution compliance (all changed files; ≤10)
Changed code files: `dot_pi/agent/extensions/goal/{index.ts, helpers.ts, helpers.test.ts, create_config.json}`.
| Principle | Verdict |
|---|---|
| I (source path) | compliant — under `dot_pi/agent/extensions/goal/` → `~/.pi/...` |
| II / IX (skills) | inapplicable — extension, not a skill |
| III (no secrets) | compliant — judge auth via model-registry; no keys in source |
| V (mise) | compliant — no dev-tool install added |
| VIII (openspec not deployed) | compliant |
**PASS**.

## Completion Decision: **green**

## Test evidence
- `bun test` → **22 pass / 0 fail / 50 expect()** (parseVerdict; parseGoalArg incl. all clear aliases; shouldStopForBudget; decideAfterEvaluation incl. clarify-I1 met-wins; normalizeGoalConfig + resolveSetting precedence; lastAssistantInfo + isInterruptedStop for abort/error).
- **Config-driven settings confirmed:** a `config.json` with `maxTurns: 3` was honored at runtime (debug log `maxTurns=3`); `create_config.json` maps to `~/.pi/agent/extensions/goal/config.json` (chezmoi `create_` — user edits preserved on re-apply).
- Extension **loads in real pi** (interactive TUI shows `[Extensions] goal`) and the `/goal` command executes + sets state (debug-log confirmed, headless + PTY).
- `agent_end` → `complete()` judge → `sendUserMessage(followUp)` continuation loop and JSON verdict parsing: **spike-validated against the live runtime** (design.md Context; FIRST-TURN-OK→SECOND-TURN-OK, clean `{"met":...}` verdict).

## Post-apply bug fixes (owner-reported)
- **Stuck working spinner on cancel** → root cause: `agent_end` re-injected a follow-up even when the turn ended `aborted`, fighting the user's interrupt. Fixed by `stopReason` detection (design D10): `aborted`/`error` now clears the goal and stops. (`goal-loop.interrupt-stops-the-loop`)
- **"No way to clear"** → `/goal clear` now also `ctx.abort()`s any in-flight turn so a running loop halts immediately.
- **Goal never met (even "echo hello world")** → root cause: the judge instruction was in `systemPrompt`, which the claude-bridge judge (runs the `claude` CLI) ignores — it answered conversationally so the verdict never parsed. Fixed by moving the instruction into the user message (design D11); probe confirmed bridge sonnet then returns `{"met":true,…}`. Transcript now also falls back to session entries when `agent_end` carries no assistant text.

## Residual / manual (honest gaps)
- **Command-triggered first turn (`/goal` → turn 1) and the live `setStatus` indicator / `notify`** are only exercisable in a human-interactive session. Every headless/PTY harness (`-p`, stdin-pipe, `expect`, `script`) processes the initial input then exits before pumping the queued `sendUserMessage`, so the very first turn was not auto-verified. The continuation loop *after* a real first turn is spike-proven; the branch logic is unit-proven. **Action:** manual interactive confirmation (tasks 6.2) before relying on it unattended.
- **Headless limitation:** unlike Claude Code's `-p` `/goal`, this loop does not self-drive in print mode (pi exits before pumping the command's first turn). Noted as a follow-up in design Open Questions.
- Pre-existing unrelated `pi-session-search` teardown crash appears in `-p` runs; not caused by this change.
