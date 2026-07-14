<!-- authored: in-session -->
# Execution Plan

## Plan step 1: Multi-review YAML list write

- **Covers:** T1.1
- **Pre-conditions:**
  - Change dir has proposal + specs; worktree not yet required for artifact commits
- **Action:**
  1. Extend `tests/opsx-models/test_opsx_models.sh` with failing cases for
     `opsx models set review a/x,b/y` and `set review a/x b/y` → newline-delimited
     resolve (cite `opsx-cli.model-config-write-surface`)
  2. Run test → expect FAIL on current scalar write
  3. Update `opsx_models` set path to parse comma/multi-arg into YAML sequence via yq
  4. Run test → expect PASS; single-token review still full-replaces to one-element list
  5. Commit (`feat: opsx models set review writes YAML lists`)
- **Verification:** `bash tests/opsx-models/test_opsx_models.sh`
- **Rollback:** revert the set-path + test hunks

## Plan step 2: Thinking suffix passthrough tests + any qualify fix

- **Covers:** T1.2
- **Pre-conditions:** Step 1 green
- **Action:**
  1. Add failing tests for `set impl cursor/composer-2.5:high` round-trip and bare
     `id:xhigh` + provider qualification (cite
     `opsx-model-config.thinking-suffix-passthrough`)
  2. Run → FAIL only if qualify strips suffix (likely already PASS for slash ids)
  3. Minimal fix in `qualify`/set if bare+suffix needs split-aware provider join
  4. Run → PASS
  5. Commit (`test/fix: preserve :thinking suffix on opsx models`)
- **Verification:** `bash tests/opsx-models/test_opsx_models.sh`
- **Rollback:** revert qualify/set + tests

## Plan step 3: Interactive picker

- **Covers:** T2.1, T2.2
- **Pre-conditions:** Steps 1–2 green (write path can store lists/suffixes)
- **Action:**
  1. Add stubbed interactive helper tests (fake `pi --list-models`, fake fzf/select,
     cite `opsx-cli.interactive-models-set`)
  2. Run → FAIL (helpers absent)
  3. Implement interactive branch in `opsx_models` set: role prompt, catalog parse,
     fzf-or-numbered, multi-select review, thinking suffix, AIS boolean; wire to
     same atomic writer as non-interactive
  4. Run → PASS; non-interactive paths unchanged
  5. Commit (`feat: interactive opsx models set picker`)
- **Verification:** `bash tests/opsx-models/test_opsx_models.sh`
- **Rollback:** remove interactive helpers; restore set usage error for missing value

## Plan step 4: Template docs

- **Covers:** T3.1
- **Pre-conditions:** Steps 1–3 green
- **Action:**
  1. Document interactive `opsx models set`, multi-review CLI list write, and
     `:thinking` suffix examples in template comments
  2. Spot-check comments match ACs
  3. Commit (`docs: opsx-models template notes for picker and suffixes`)
- **Verification:** template comment review; suite still green
- **Rollback:** revert template file

## Completion Verification

- `bash tests/opsx-models/test_opsx_models.sh` exits 0
- `opsx gate ease-opsx-models-ux --worktree <path>` progresses past validation
  `opsx-models-tests` once implementation lands

## Manual Adjustments

- Plain-M: no standalone clarify/design/analyze; decisions frozen in intent +
  proposal Open Questions.
- Execution Mode standard (not tdd-required): plan uses ordered TDD-flavored
  steps as discipline, not a gate-enforced red/green cycle.
- Delegation Mode subagent-required: apply may dispatch plan steps via
  pi-subagents with `impl` model when configured.
