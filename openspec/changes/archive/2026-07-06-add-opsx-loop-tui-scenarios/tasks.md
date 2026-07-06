<!-- authored: in-session -->

## 1. Harness scaffolding

- [x] 1.1 Add `tests/opsx-tui` scenario docs, runner, and private tmux helper library.
  - intent: feature
  - files_allowed:
      - tests/opsx-tui/**
  - allow_new_files: true

- [x] 1.2 Add deterministic fixtures for fake `opsx`, temp OpenSpec repos, pane-log capture, and optional fake provider turn logging.
  - intent: feature
  - files_allowed:
      - tests/opsx-tui/**
  - allow_new_files: true

## 2. Command visibility scenarios

- [x] 2.1 Add real-TUI scenarios for bare/status/clear command visibility.
  - intent: feature
  - files_allowed:
      - tests/opsx-tui/**
      - dot_pi/agent/extensions/opsx-loop/**
  - allow_new_files: true

- [x] 2.2 Add real-TUI scenarios for `/opsx-loop models` argument preservation and pane-visible output.
  - intent: feature
  - files_allowed:
      - tests/opsx-tui/**
      - dot_pi/agent/extensions/opsx-loop/**
  - allow_new_files: true

## 3. Loop-state scenarios

- [x] 3.1 Add real-TUI scenarios for already-green and red-arm-clear loop behavior.
  - intent: feature
  - files_allowed:
      - tests/opsx-tui/**
      - dot_pi/agent/extensions/opsx-loop/**
  - allow_new_files: true

- [x] 3.2 Add real-TUI scenarios for goal distill pause and loop hold/re-arm behavior.
  - intent: feature
  - files_allowed:
      - tests/opsx-tui/**
      - dot_pi/agent/extensions/opsx-loop/**
  - allow_new_files: true

## 4. Verification integration

- [x] 4.1 Document optional real-model smoke behavior and keep it skipped by default.
  - intent: feature
  - files_allowed:
      - tests/opsx-tui/**
      - openspec/changes/add-opsx-loop-tui-scenarios/**
  - allow_new_files: true

- [x] 4.2 Wire the scenario runner into retained validation evidence without making real provider credentials mandatory.
  - intent: infra
  - files_allowed:
      - tests/opsx-tui/**
      - openspec/changes/add-opsx-loop-tui-scenarios/**
      - dot_local/bin/executable_opsx
      - tests/opsx-*/**
  - allow_new_files: true
