<!-- authored: in-session -->
# Tasks — ease-opsx-models-ux

## 1. Multi-review write + suffix round-trip

- [x] 1.1 Fix non-interactive `opsx models set review` to parse comma-separated and/or multiple positional tokens into a YAML list (full replace); keep atomic temp+mv writes
  - intent: feature
  - files_allowed:
      - dot_local/bin/executable_opsx
      - tests/opsx-models/**
  - allow_new_files: true
- [x] 1.2 Ensure suffix-bearing model ids (`provider/id:high`) round-trip through set/get/resolve without stripping; add hermetic tests citing `opsx-cli.model-config-write-surface` and `opsx-model-config.thinking-suffix-passthrough`
  - intent: feature
  - files_allowed:
      - dot_local/bin/executable_opsx
      - tests/opsx-models/**
  - allow_new_files: true

## 2. Interactive `opsx models set`

- [x] 2.1 Implement interactive path for bare `opsx models set` and role-only `opsx models set <role>` on TTY: role pick, `pi --list-models` catalog, fzf-or-numbered select, review multi-select, thinking suffix prompt, author-in-session boolean prompt; actionable fail when `pi` missing/empty catalog
  - intent: feature
  - files_allowed:
      - dot_local/bin/executable_opsx
      - tests/opsx-models/**
  - allow_new_files: true
- [x] 2.2 Add hermetic tests for interactive helpers (stub `pi`/`fzf`/TTY) citing `opsx-cli.interactive-models-set`; keep non-interactive escape hatch covered
  - intent: feature
  - files_allowed:
      - tests/opsx-models/**
      - dot_local/bin/executable_opsx
  - allow_new_files: true

## 3. Docs

- [x] 3.1 Update schema template `opsx-models.yaml` comments for interactive set, multi-review CLI list write, and `:thinking` suffix examples
  - intent: feature
  - files_allowed:
      - dot_local/share/openspec/schemas/opsx-superpowers/templates/opsx-models.yaml
  - allow_new_files: false
