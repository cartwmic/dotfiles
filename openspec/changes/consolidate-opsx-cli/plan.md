<!-- authored: in-session -->
# Execution Plan

Execution Mode = standard (not tdd-required) → ordered lists. One commit per step.

## Plan step 1: Build `opsx` dispatcher + retire legacy scripts

- **Covers:** T1.1, T1.2
- **Pre-conditions:** worktree `opsx/consolidate-opsx-cli` created; Diff Base SHA + Worktree Path recorded in review.md.
- **Action:**
  1. Write `executable_opsx`: dispatcher + `gate_*`/`models_*`/`loop_*` functions ported from the three scripts (exit→return, prefixed/local globals, per-subcommand usage/PROG, in-file model resolution).
  2. `bash -n dot_local/bin/executable_opsx`.
  3. `git rm` the three legacy scripts; add `.chezmoiremove` with the three deployed bin paths.
  4. Commit (`refactor(opsx): fold gate/models/loop into one opsx multitool`).
- **Verification:** `bash -n` clean; dispatcher routes known/unknown/missing subcommand.
- **Rollback:** `git checkout` the worktree; legacy scripts return.

## Plan step 2: `opsx models` write surface

- **Covers:** T2.1
- **Pre-conditions:** step 1 merged in worktree.
- **Action:** implement `set/get/list` (roles incl. author-in-session, layers, atomic+failure, create-if-absent, yq -i, set-review warn, project-root discovery); commit (`feat(opsx): opsx models set/get/list write surface`).
- **Verification:** new `tests/opsx-cli` write-surface cases pass (authored in step 5, or smoke inline).
- **Rollback:** revert the step commit.

## Plan step 3: Migrate skills + schema/templates

- **Covers:** T3.1
- **Pre-conditions:** steps 1-2.
- **Action:** rewrite legacy invocations → `opsx <sub>` across canonical skills + schema; document write surface + `/opsx-loop models`; commit (`docs(opsx): migrate skills+schema to opsx subcommands`).
- **Verification:** token-level legacy scan over caller paths → empty.
- **Rollback:** revert.

## Plan step 4: pi extension migration + bug fixes

- **Covers:** T4.1
- **Pre-conditions:** steps 1-3.
- **Action:** spawn-name migration; parser rework; `/opsx-loop models` wrapper; worktree re-resolution; stall detection; goal test ref; helper unit tests; commit (`feat(opsx-loop): models subcommand, parser/worktree/stall fixes`).
- **Verification:** `bun test helpers.test.ts`; `bun build index.ts --target node --outfile /dev/null`.
- **Rollback:** revert.

## Plan step 5: Tests retarget + opsx-cli suite

- **Covers:** T5.1
- **Pre-conditions:** steps 1-4.
- **Action:** retarget gate/models suites to `opsx <sub>`; add `tests/opsx-cli/test_opsx_cli.sh`; commit (`test(opsx): retarget suites + add opsx-cli dispatch/write tests`).
- **Verification:** all shell suites green against `executable_opsx <sub>`.
- **Rollback:** revert.

## Plan step 6: Verify, code-review, gate

- **Covers:** T6.1
- **Pre-conditions:** steps 1-5; all suites green.
- **Action:** run full verify (suites + bash -n + bun + token scan + `openspec validate --strict`); author verify.md; dispatch blind multi-model code-review (opus + gpt-5.5) over `Diff Base..HEAD`; author code-review.md; seal; `opsx gate consolidate-opsx-cli --worktree <path>`.
- **Verification:** GATE-PASS exit 0.
- **Rollback:** if gate red, fix earliest failure; verdicts stay uncommitted until green.
