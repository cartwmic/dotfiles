# Execution Plan

Execution Mode = standard (test-after). Worktree-always: implement on
`opsx/add-opsx-loop-context-elision`, gate with `--worktree <path>`,
`bun test` in `dot_pi/agent/extensions/opsx-loop/` after each step.

## Plan step 1: pure elision helpers

- **Covers:** T1.1, T1.2, T1.3
- **Pre-conditions:**
  - Worktree created; `helpers.ts` present with existing `resolveCompact*` helpers.
- **Action:**
  1. Add `resolveElideThresholdTokens` + `OPSX_ELIDE_AT_*` resolution (reuse
     `resolveCompactPercent`/`resolveCompactTokens` shape).
  2. Add `elideBoundary(total, keepRecent, band)` band-quantized boundary.
  3. Add `elideToolResultBodies(messages, opts)` returning a new fail-closed view;
     pairing-aware, non-mutating.
  4. `bun test` → expect existing suite still green.
- **Verification:**
  - `bun test` (helpers.test.ts) — all pass.
- **Rollback:**
  - `git restore dot_pi/agent/extensions/opsx-loop/helpers.ts`.

## Plan step 2: extension wiring

- **Covers:** T2.1, T2.2, T2.3
- **Pre-conditions:**
  - Step 1 helpers exported.
- **Action:**
  1. Add `elided?: boolean` to `LoopState`.
  2. Register the `context` event handler (guarded, active-loop-only, threshold-gated).
  3. Couple `agent_end`: force compact when `loop.elided`; reset flag at run start.
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
  1. Write unit tests for threshold/boundary/elision helpers citing canonical AC IDs.
  2. `bun test` → expect PASS.
  3. Commit (`feat(opsx-loop): mid-run context elision`).
- **Verification:**
  - `bun test` all green; new tests cover each new AC.
- **Rollback:**
  - `git restore dot_pi/agent/extensions/opsx-loop/helpers.test.ts`.
