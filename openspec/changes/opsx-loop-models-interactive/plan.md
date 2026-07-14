<!-- authored: in-session -->
# Execution Plan

## Plan step 1: CLI per-model review thinking

- **Covers:** T1.1, T1.2
- **Pre-conditions:**
  - Worktree on `opsx/opsx-loop-models-interactive`
  - Existing hermetic interactive stubs in `tests/opsx-models/`
- **Action:**
  1. Add failing hermetic test: interactive review picks two models with
     distinct thinking levels → YAML list has distinct `:<suffix>` entries
     (cite `opsx-cli.interactive-models-set`)
  2. Run `tests/opsx-models/test_opsx_models.sh` → expect FAIL on new case
  3. In `interactive_set`, for `review`: after each pick inside `pick_models`
     (or wrap the sequential loop) call `pick_thinking_level` and append
     suffix to that id before next pick; author/impl keep single
     `pick_thinking_level` after `pick_models`
  4. Re-run suite → PASS
  5. Commit (`feat(opsx): per-model thinking on interactive review set`)
- **Verification:** `tests/opsx-models` green; spot-check non-interactive
  multi-arg suffixes unchanged
- **Rollback:** revert commit; restore shared `append_thinking_suffix` after
  multi-pick

## Plan step 2: Catalog helper + filtered picker

- **Covers:** T2.1, T2.2
- **Pre-conditions:** Step 1 landed or independent; pi TUI SelectList available
  from extension deps
- **Action:**
  1. Unit tests for catalog parse (fixture `pi --list-models` sample) and
     substring filter matching mid-id (cite
     `opsx-loop.model-config-subcommand`)
  2. Run extension tests → FAIL
  3. Implement `listModelsCatalog` (spawn `pi --list-models`, longer timeout)
     + custom filtered SelectList (`includes` / contains, case-insensitive)
  4. Tests PASS
  5. Commit (`feat(opsx-loop): catalog parse + substring model picker`)
- **Verification:** extension unit tests green
- **Rollback:** revert commit; remove helper modules

## Plan step 3: Wire interactive `/opsx-loop models set`

- **Covers:** T2.3, T2.4
- **Pre-conditions:** Step 2 helpers available
- **Action:**
  1. Tests for bare/role-only routing when UI mocked: builds
     `opsx models set review a:high b:xhigh` argv; value-bearing passthrough;
     no-UI bare set does not hang (cite
     `opsx-loop.model-config-subcommand`)
  2. Tests FAIL
  3. Implement interactive flow in `runModels` / slash handler; final write
     only via `opsx models set …`; never write YAML from extension
  4. Tests PASS
  5. Commit (`feat(opsx-loop): interactive models set via Path B`)
- **Verification:** extension unit tests; manual smoke optional
- **Rollback:** revert; restore thin-wrapper-only `runModels`

## Plan step 4: Full validation

- **Covers:** T3.1
- **Pre-conditions:** Steps 1–3 committed
- **Action:**
  1. Run `tests/opsx-models` and extension test suite
  2. Fix any regressions within files_allowed
  3. Confirm AC ID strings present in new tests
  4. Commit only if fixes needed (`test: …` / `fix: …`)
- **Verification:** both suites green
- **Rollback:** revert fix commits

## Deterministic analyze note (plain-M)

Proposal Open Questions resolved; no standalone `analyze.md` / `clarify.md` /
`design.md` (decision-gated design skipped — forks frozen in intent).
