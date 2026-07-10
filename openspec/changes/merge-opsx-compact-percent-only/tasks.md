## 1. Helpers: percent-only threshold

- [ ] 1.1 Rewrite the Lever A threshold helpers in helpers.ts: delete `resolveCompactTokens`; change `resolveCompactPercent` default 33 → 50; shrink `resolveCompactThresholdTokens` to `(contextWindow, pctRaw)` computing `ceil(pct/100 × window)` (undefined when the percent term is off or the window is non-positive/unknown); simplify `describeCompactPolicy(pctRaw)` to the single-term line; update the Lever A comment block (max-formula prose dies)
  - intent: refactor
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/helpers.ts
  - allow_new_files: false

## 2. Call sites

- [ ] 2.1 Update index.ts call sites: threshold computation (~L428–431) and the loop-arm policy notify (~L691) drop the `OPSX_COMPACT_AT_TOKENS` argument; no remaining reference to `OPSX_COMPACT_AT_TOKENS` anywhere in the extension
  - intent: refactor
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/index.ts
  - allow_new_files: false

## 3. Tests

- [ ] 3.1 Rewrite the compaction-threshold describe block in helpers.test.ts for percent-only semantics, citing the new AC IDs (`opsx-loop-compaction-guard.percent-only-compaction-trigger`, `.default-on-with-explicit-off-only`, `.garbage-falls-back-to-default`, `.default-layers-above-elision-budget`, `.policy-notify-describes-single-term`): default-50 threshold, configured percent, off tokens disable, garbage/out-of-range fall back to 50, unknown window → undefined, `OPSX_COMPACT_AT_TOKENS` ignored, policy line single-term/off, default 50 > elide keep 40
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/helpers.test.ts
  - allow_new_files: false

- [ ] 3.2 Full validation: `bun test` in dot_pi/agent/extensions/opsx-loop passes with zero failures
  - intent: fix
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/**
  - allow_new_files: false
