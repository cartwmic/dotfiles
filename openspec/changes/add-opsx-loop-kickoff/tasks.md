# Tasks — add-opsx-loop-kickoff

## 1. opsx-loop pi extension

- [x] 1.1 Pure helpers: budget parse from review.md front-matter, verdict-from-exit-code, `/opsx-loop` arg parse (status/clear aliases/set)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/helpers.ts
- [x] 1.2 Extension index.ts: register `/opsx-loop`; agent_end loop (run opsx-gate judge, continue/stop, budget, interrupt-stops, evaluating-guard); status/clear subcommands; status indicator
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/index.ts
- [x] 1.3 Unit tests for the pure helpers (bun test)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/helpers.test.ts

## 2. Verify

- [x] 2.1 Confirm goal extension unchanged; bun test green; transpile-check index.ts
  - intent: feature
