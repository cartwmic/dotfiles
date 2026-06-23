# Plan — add-opsx-loop-kickoff

## Step 1 — Pure helpers (TDD)
- **Covers:** T1.1, T1.3
- **Action:** write `helpers.ts` (`parseLoopBudget`, `verdictFromExit`, `parseLoopArg`) + failing tests; implement; `bun test` green.
- **Verification:** `bun test helpers.test.ts` all pass.
- **Rollback:** revert the extension dir.

## Step 2 — Extension wiring
- **Covers:** T1.2
- **Action:** `index.ts` — `pi.registerCommand("opsx-loop", …)`; on set, resolve worktree + budget from review.md, inject worker turn (followUp) pointing at the openspec-loop skill; `pi.on("agent_end")` runs `opsx-gate <change> [--worktree]` via spawn, exit 0 → achieved (notify ready to archive), else inject next turn with the gate report, budget-bounded; interrupt/error stops; `evaluating` re-entrancy guard; status/clear subcommands + status indicator.
- **Verification:** transpile-check (external pi deps unresolved is expected); goal extension untouched (`git diff --stat` shows no goal/ changes).
- **Rollback:** revert index.ts.

## Step 3 — Verify + close
- **Covers:** T2.1
- **Action:** run opsx-gate against the change; produce verify.md + code-review.md (post-impl review over the diff); seal verdicts uncommitted; gate green.
- **Verification:** `opsx-gate add-opsx-loop-kickoff --worktree <wt>` → GATE-PASS.
- **Rollback:** worktree preserved on failure.
