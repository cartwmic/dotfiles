# Execution Plan

## Plan step 1: percent-only helpers

- **Covers:** T1.1
- **Pre-conditions:**
  - `opsx/merge-opsx-compact-percent-only` worktree created; Diff Base SHA captured in review.md
- **Action:**
  1. In `helpers.ts`, delete `resolveCompactTokens` and its doc comment
  2. Change `resolveCompactPercent` fallback constant 33 → 50 (all three fallback returns + doc comment)
  3. Shrink `resolveCompactThresholdTokens(contextWindow, pctRaw, tokRaw)` → `(contextWindow, pctRaw)`: return `Math.ceil((pct/100) × contextWindow)` when pct non-null and window positive/finite; otherwise `undefined`
  4. Simplify `describeCompactPolicy(pctRaw, tokRaw)` → `(pctRaw)`: `"compaction guard: off"` when pct null; else `"compaction guard: compact at ≥ <pct>% window"`
  5. Update the Lever A section comment: percent-only trigger, default 50, single-step off, garbage→default
- **Verification:**
  - `bun test helpers.test.ts` (compaction block will fail until step 3 — expected mid-plan)
  - `grep -c OPSX_COMPACT_AT_TOKENS helpers.ts` → 0
- **Rollback:**
  - `git checkout -- helpers.ts` on the worktree branch

## Plan step 2: call sites

- **Covers:** T2.1
- **Pre-conditions:** step 1 landed
- **Action:**
  1. `index.ts` threshold call: `resolveCompactThresholdTokens(contextWindow, process.env.OPSX_COMPACT_AT_PERCENT)` — drop the tokens arg
  2. `index.ts` notify call: `describeCompactPolicy(process.env.OPSX_COMPACT_AT_PERCENT)` — drop the tokens arg
  3. Update the Lever A comment near L386 if it references the token floor
- **Verification:**
  - `grep -c OPSX_COMPACT_AT_TOKENS index.ts` → 0
  - `bunx tsc --noEmit` equivalent unavailable; rely on bun test + grep
- **Rollback:**
  - `git checkout -- index.ts` on the worktree branch

## Plan step 3: tests rewritten for percent-only

- **Covers:** T3.1, T3.2
- **Pre-conditions:** steps 1–2 landed
- **Action:**
  1. Rewrite the `compaction threshold resolution` describe block: cases for default 50 (unset/empty), configured percent, each off token (`off`/`none`/`false`/`0`, case/whitespace variants), garbage (`banana`, `50%`, `1.5`), out-of-range (`0` is off; `-1`, `101` → default 50), unknown/non-positive window → undefined, `describeCompactPolicy` single-term + off lines, and default 50 > default elide keep 40 (layering)
  2. Cite AC IDs verbatim in comments/strings per the verify gate's literal grep
  3. Run `bun test` — all suites green
- **Verification:**
  - `bun test` exit 0, zero failures
  - `grep -rc OPSX_COMPACT_AT_TOKENS .` → only spec/archive references outside the extension dir; 0 within dot_pi/agent/extensions/opsx-loop
- **Rollback:**
  - `git checkout -- helpers.test.ts` on the worktree branch

## Completion Verification

- `bun test` in `dot_pi/agent/extensions/opsx-loop/` → exit 0, 0 failures
- `grep -rn "OPSX_COMPACT_AT_TOKENS\|resolveCompactTokens" dot_pi/agent/extensions/opsx-loop/` → no matches

## Manual Adjustments

- Execution Mode standard (not TDD): the change is a behavior-preserving-on-200k
  refactor with a rewritten test block; tests land in the same plan as the code with
  the full suite as the completion check.
