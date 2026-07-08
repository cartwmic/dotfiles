# Execution Plan

Execution Mode = standard (test-after). Worktree-always: implement on
`opsx/refine-opsx-elision-token-budget`, gate with `--worktree <path>`,
`bun test` in `dot_pi/agent/extensions/opsx-loop/` after each step. Branches from a
main that already contains the shipped turn-count elision (archived
`add-opsx-loop-context-elision`), so this is a pure supersession refactor.

## Plan step 1: token-budget helpers

- **Covers:** T1.1, T1.2, T1.3, T1.4, T1.5
- **Pre-conditions:**
  - Worktree created; `helpers.ts` present with the shipped `resolveElide*` /
    `elideBoundary` / `elideToolResultBodies` helpers.
- **Action:**
  1. Remove the retired turn-count resolvers, `elideBoundary`, and the
     `OPSX_ELIDE_AT_*` / `OPSX_ELIDE_*_TURNS` reads.
  2. Add `resolveElideKeepPercent` / `resolveElideBandPercent` and the
     window-relative `resolveElideMaxKeepTokens` / `resolveElideBandTokens`.
  3. Add the per-turn char/4 token estimator and `tokenBudgetBoundary(...)`.
  4. Adapt `elideToolResultBodies` to consume the token-snapped boundary; keep the
     fail-closed pairing/structural guards and non-mutation.
  5. `bun test` → expect the suite still green after the test rewrite in step 3.
- **Verification:**
  - `bun test` (helpers.test.ts) — all pass.
- **Rollback:**
  - `git restore dot_pi/agent/extensions/opsx-loop/helpers.ts`.

## Plan step 2: extension wiring

- **Covers:** T2.1, T2.2, T2.3
- **Pre-conditions:**
  - Step 1 helpers exported.
- **Action:**
  1. Rewire the `context` handler to resolve `maxKeep`/`band` from the live window,
     gate on `total > maxKeep + band`, and call the token-budget boundary.
  2. Add the `if (session.compacting) return undefined;` guard.
  3. Consume/clear `session.elided` on the distill (`awaitingChange`) path.
  4. `bun test`.
- **Verification:**
  - `bun test` green; `chezmoi diff` sane; no re-enable of `compaction.enabled`.
- **Rollback:**
  - `git restore dot_pi/agent/extensions/opsx-loop/index.ts`.

## Plan step 3: tests

- **Covers:** T3.1
- **Pre-conditions:**
  - Steps 1–2 implemented.
- **Action:**
  1. Replace the turn-count helper tests with token-budget-boundary tests citing
     canonical AC IDs.
  2. `bun test` → expect PASS.
  3. Commit (`feat(opsx-loop): token-budget context-elision boundary`).
- **Verification:**
  - `bun test` all green; new tests cover each new/modified AC.
- **Rollback:**
  - `git restore dot_pi/agent/extensions/opsx-loop/helpers.test.ts`.
