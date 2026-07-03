# Execution Plan

Execution Mode = standard (ordered steps, not TDD micro-tasks): the diff is
markdown discipline prose in templates + skills; validators are the repo's
opsx-gates.yaml set.

## Plan step 1: Templates

- **Covers:** T1.1, T1.2, T1.3
- **Pre-conditions:** worktree created, Diff Base SHA recorded in review.md
- **Action:**
  1. review.md template: `review_max_rounds` commented front-matter key with
     default-5 note; `Scope Expansions` section (entry = what widened + evidence
     + date).
  2. code-review.md template: verdict-contract/rubric header; Round tracker
     gains per-reviewer verdicts, reviewed HEAD, consolidated (max) counts;
     `review_mode` vocab += `disclosure-consensus`; `waived_by_user` slot.
  3. New follow-ups.md template per spec (finding, severity, origin, routing
     reason, user-waived marker).
  4. Commit (`docs(opsx): …` subject ≤72).
- **Verification:** `openspec validate --changes --strict`; manual read-back of
  templates against `opsx-workflow-schema` delta ACs
- **Rollback:** revert commit

## Plan step 2: openspec-loop skill

- **Covers:** T2.1
- **Pre-conditions:** step 1 merged wording (field names stable)
- **Action:**
  1. Add "Review convergence (mandatory)" section to canonical
     openspec-loop/SKILL.md: ledger, stop conditions, disclosure round,
     landing (waiver re-seal, budget extension, loop halt), widening protocol,
     surface audit, model stability, red flags.
  2. Commit.
- **Verification:** grep cross-check versus `opsx-review-convergence` delta ACs
  (budget default, trigger wording, field names)
- **Rollback:** revert commit

## Plan step 3: apply-mode reference

- **Covers:** T3.1
- **Pre-conditions:** step 2 terminology final
- **Action:**
  1. Extend opsx-superpowers-mode.md code-review production section: contract +
     rubric in dispatch prompt, severity-floor verdict, ledger sealing,
     follow-ups routing.
  2. Commit.
- **Verification:** grep cross-check versus `opsx-post-impl-review` delta ACs
- **Rollback:** revert commit

## Plan step 4: consistency + full validation

- **Covers:** T4.1, T4.2
- **Pre-conditions:** steps 1-3 committed
- **Action:**
  1. Contradiction grep across edited files (stop conditions, default 5,
     disclosure trigger, `waived_by_user`); reconcile any drift.
  2. Confirm zero edits under `dot_local/bin/executable_opsx` gate decision
     logic and `dot_pi/agent/extensions/opsx-loop/`.
  3. Run all opsx-gates.yaml validators; fix regressions; commit fixes.
- **Verification:** all required gates exit 0
- **Rollback:** revert offending commit(s)

## Completion Verification

- `opsx gate add-opsx-review-convergence` → all mechanical checks green
  (validation via openspec-validate + gate/CLI/models/extension tests + shell
  syntax), then code-review (gating-required, multi-model) and doneness judge
  green.

## Manual Adjustments

- None. standard execution; worktree-required per review.md.
