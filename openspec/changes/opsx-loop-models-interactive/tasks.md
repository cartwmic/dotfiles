<!-- authored: in-session -->
## 1. CLI per-model review thinking

- [ ] 1.1 Change interactive review thinking so each sequential pick gets its own `pick_thinking_level` before the next pick; keep author/impl as one shared prompt after the single pick
  - intent: feature
  - files_allowed:
      - dot_local/bin/executable_opsx
  - allow_new_files: false

- [ ] 1.2 Add hermetic test(s) that interactive review with mixed thinking levels stores distinct per-entry suffixes (cite `opsx-cli.interactive-models-set`)
  - intent: feature
  - files_allowed:
      - tests/opsx-models/**
      - tests/opsx-cli/**
  - allow_new_files: true

## 2. Extension Path B interactive set

- [ ] 2.1 Parse `pi --list-models` into `provider/id` catalog helper; actionable error on empty/fail; allow longer timeout than the 10s `runModels` default for catalog fetch
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/**
  - allow_new_files: true

- [ ] 2.2 Implement substring/contains-filtered model picker via `ctx.ui.custom` (not startsWith-only stock SelectList)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/**
  - allow_new_files: true

- [ ] 2.3 Wire bare `/opsx-loop models set` and role-only `set <role>` when `hasUI`: role → pick(s) → per-model thinking for review / one thinking for author|impl → `opsx models set …` write; value-bearing set stays thin passthrough; no-UI does not hang
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/**
  - allow_new_files: true

- [ ] 2.4 Extension unit tests for catalog parse, interactive arg routing, and CLI write args with mixed review suffixes (cite `opsx-loop.model-config-subcommand`)
  - intent: feature
  - files_allowed:
      - dot_pi/agent/extensions/opsx-loop/**
  - allow_new_files: true

## 3. Validation wrap-up

- [ ] 3.1 Run `tests/opsx-models` (+ opsx-cli if touched) and extension unit tests; fix failures without weakening ACs
  - intent: infra
  - files_allowed:
      - tests/opsx-models/**
      - tests/opsx-cli/**
      - dot_pi/agent/extensions/opsx-loop/**
      - dot_local/bin/executable_opsx
  - allow_new_files: false
