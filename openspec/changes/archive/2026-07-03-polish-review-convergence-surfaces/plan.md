# Execution Plan

Execution Mode = standard. Four-file prose/test polish.

## Plan step 1: prose surfaces + test

- **Covers:** T1.1, T1.2, T2.1
- **Pre-conditions:** worktree created, Diff Base SHA recorded in review.md
- **Action:**
  1. Red-flag line into SKILL.md Review-convergence section + apply-mode
     convergence bullet.
  2. Template heading rename (manifest-check comment preserved).
  3. Surface test: `set -e` comment + 3 new assertions
     (opsx-review-convergence.prose-surface-fidelity).
  4. Commit (`docs(skills)`/`fix(opsx)` subjects ≤72).
- **Verification:** surface test green; `openspec validate --changes --strict`
- **Rollback:** revert commit

## Plan step 2: validation

- **Covers:** T2.2
- **Action:** run all opsx-gates.yaml validators; fix regressions; commit.
- **Verification:** all required gates exit 0
- **Rollback:** revert offending commit

## Completion Verification

- `opsx gate polish-review-convergence-surfaces --worktree <path>` green, then
  gating multi-model code review pass.

## Manual Adjustments

- None.
