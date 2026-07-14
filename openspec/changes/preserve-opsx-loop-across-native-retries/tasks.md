## 1. Retry-aware loop lifecycle

- [x] 1.1 Record an errored low-level attempt on the active `LoopState` and return without clearing, gating, incrementing loop/stall budgets, or injecting an extension-owned retry; keep explicit abort immediately terminal and clear a pending error on the next clean attempt. (AC `opsx-loop.interrupt-or-error-stops-the-loop`)
  - intent: fix
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/index.ts
  - allow_new_files: false

- [x] 1.2 Handle `agent_settled` only when the same active loop still owns an unresolved pending error: preserve the existing one-shot context-overflow compact-and-retry path, otherwise stop visibly with the worktree preserved; make stale settlement after clear/replacement/re-arm a no-op by construction. (AC `opsx-loop.interrupt-or-error-stops-the-loop`)
  - intent: fix
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/index.ts
  - allow_new_files: false

## 2. Native-retry lifecycle regression coverage

- [x] 2.1 Extend the deterministic fake OpenAI server with an opt-in per-request HTTP status sequence while retaining existing all-success behavior for every current scenario. (AC `opsx-loop.interrupt-or-error-stops-the-loop`)
  - intent: feature
  - files_allowed:
      - tests/opsx-tui/fixtures/fake-openai-server.mjs
  - allow_new_files: false

- [x] 2.2 Add and register a real-Pi TUI scenario where the provider fails transiently, Pi retries successfully, the loop stays armed, and the successful boundary reaches exactly one normal gate-green landing; document the scenario and deterministic signals. (AC `opsx-loop.interrupt-or-error-stops-the-loop`)
  - intent: feature
  - files_allowed:
      - tests/opsx-tui/SCENARIOS.md
      - tests/opsx-tui/scripts/run-all-scenarios.sh
      - tests/opsx-tui/scripts/run-scenario-s07-native-retry.sh
  - allow_new_files: true

- [ ] 2.3 Add a final-error TUI scenario or equivalent deterministic lifecycle assertion proving exhausted native retries produce one visible stop and no opsx-owned provider retry, and retain regression coverage for explicit clear/interrupt behavior. (AC `opsx-loop.interrupt-or-error-stops-the-loop`)
  - intent: feature
  - files_allowed:
      - tests/opsx-tui/SCENARIOS.md
      - tests/opsx-tui/scripts/run-all-scenarios.sh
      - tests/opsx-tui/scripts/run-scenario-s08-retry-exhausted.sh
      - tests/opsx-tui/scripts/run-scenario-s06-interrupt-optional.sh
  - allow_new_files: true

## 3. Validation and spec traceability

- [ ] 3.1 Run focused opsx-loop unit tests and all deterministic default TUI scenarios; record AC-to-test evidence and commands in `verify.md` without weakening existing gates. (AC `opsx-loop.interrupt-or-error-stops-the-loop`)
  - intent: fix
  - files_allowed:
      - openspec/changes/preserve-opsx-loop-across-native-retries/verify.md
  - allow_new_files: true

<!-- authored: in-session -->
