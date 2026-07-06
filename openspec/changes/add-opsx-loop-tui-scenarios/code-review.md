# Code Review

**Change:** add-opsx-loop-tui-scenarios
**Verdict:** pass
**review_mode:** adversarial-multimodel
**reviewer-provenance:** pi-subagents reviewer: claude-bridge/claude-opus-4-8 (/tmp/opsx-cr-add-opsx-loop-tui-scenarios-claude-r3.md); openai-codex/gpt-5.5 (/tmp/opsx-cr-add-opsx-loop-tui-scenarios-gpt-r3b.md)
**Diff Base SHA:** 728884b4ed6cf2e83dafba9f01cd000f816e962c
**Reviewed Range:** 728884b4ed6cf2e83dafba9f01cd000f816e962c..17c6016dae7002ab6a99373ad477fd0ed3593ab9
**Attested HEAD:** 17c6016dae7002ab6a99373ad477fd0ed3593ab9
**Baseline:** intent.md + proposal + specs + design + plan + tasks status
**Generated:** 2026-07-06

## Verdict contract

Baseline-bounded review: reviewers may fail only for frozen-baseline violations or objective correctness/security defects. P0/P1 gate; P2/P3 advisory only.

## Round tracker

| Round | Mode | P0 | P1 | P2 | P3 | Reviewer verdicts | Reviewed HEAD |
|---|---|---|---|---|---|---|---|
| 1 | blind | 0 | 2 | 1 | 4 | claude-bridge/claude-opus-4-8:pass openai-codex/gpt-5.5:fail | 646d39e3156ab811f464be2121057080c801e131 |
| 2 | blind | 0 | 0 | 0 | 3 | claude-bridge/claude-opus-4-8:pass openai-codex/gpt-5.5:pass | 17c6016dae7002ab6a99373ad477fd0ed3593ab9 |

Invalid dispatch note: an earlier attempt introduced integration-checkout `progress.md` outside the read-only window carve-outs, so that attempt was voided, surgically restored by deleting only `progress.md`, and excluded from the ledger/budget.

## Findings

| # | Finding | Severity | Status |
|---|---|---|---|
| 1 | Round 1: red-arm-clear scenario did not prove `/opsx-loop clear` prevents further continuation after the delayed provider turn completed. Baseline: `opsx-loop.tui-scenarios-exercise-deterministic-loop-states`; evidence: `tests/opsx-tui/scripts/run-scenario-s03-red-arm-clear.sh`. | P1 | fixed |
| 2 | Round 1: fake `opsx` logs recorded argv/cwd but not relevant env values. Baseline: `opsx-loop.scenario-harness-is-isolated-and-signal-driven`; evidence: `tests/opsx-tui/fixtures/fake-opsx.sh`. | P1 | fixed |
| 3 | Explicit `/opsx-loop models list` is not separately sent; bare `/opsx-loop models` exercises the list path and `/opsx-loop models set ...` exercises argument preservation. | P3 | open |
| 4 | Task 4.2 wiring is documentation/retained evidence only; runner is not added to the deterministic opsx gate. This matches the baseline's optional/default-local wording. | P3 | open |
| 5 | Some pane regexes are line-oriented and may need adjustment if future notification text exceeds the fixed 180-column pane width. | P3 | open |

## Applied fixes

- `17c6016dae7002ab6a99373ad477fd0ed3593ab9` — added fake `opsx` env logging, added a provider-log stability assertion proving clear prevents further continuation, and kept the full TUI suite passing.

## Residual risks

- Default TUI scenarios depend on local `pi`, `tmux`, and `node` being installed; failures are loud, not silent.
- Optional interrupt timing remains opt-in via `OPSX_TUI_ENABLE_INTERRUPT=1`.
- Advisory P3 findings are recorded for follow-up consideration but do not gate.

## Verdict rationale

Both counted blind reviewers attested the reviewed worktree path and current HEAD. The final reviewed range is confined to `tests/opsx-tui/**` plus `tasks.md` checkbox flips, with no frozen-baseline artifact edits. The suite launches real Pi in private tmux servers, uses fake local provider/`opsx` fixtures, asserts pane-visible command behavior, records argv/cwd/env, and passes the default TUI run plus structural/unit validators. No open P0/P1 findings remain, so the adversarial multi-model verdict is pass.
