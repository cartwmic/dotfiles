# Verify

**Generated:** 2026-06-25 by openspec-apply-change (opsx-superpowers, Scale L)
**Change:** consolidate-opsx-cli
**Diff Base SHA:** 184e2556b47d1583a15ac32b1be64822fa913ace
**Reviewed Range:** 184e2556b47d1583a15ac32b1be64822fa913ace..4cb5306

## Completion Decision

**Status:** green

## Checks

| # | Check | Status | Details |
|---|---|---|---|
| 1 | Structural validation (`openspec validate --strict`) | pass | `Change 'consolidate-opsx-cli' is valid` |
| 2 | Task completion (zero `- [ ]` in tasks.md) | pass | 7 tasks checked, 0 unchecked |
| 3 | Delta vs current spec coherence | pass | 1 new capability (opsx-cli, 3 reqs) + 6 MODIFIED deltas; rename-only deltas restate full content, behavior unchanged |
| 4 | Commit hygiene (subject ≤72; body explains why) | pass | all subjects in range ≤72 (max 68); BREAKING CHANGE trailer on the multitool commit |
| 5 | AC↔test mapping (canonical IDs) | pass | forward: 28/28 AC IDs cited in diff files (tests/code/tasks); reverse: new tests cite their IDs |
| 6 | Constitution compliance audit | pass | I (chezmoi+`.chezmoiremove`), II (canonical skills), VIII (openspec not deployed), IX (adversarial review run) — see analyze.md Check 1 |

## Check 5 detail — AC↔test mapping

Forward map (every change-spec Requirement → ≥1 diff file contains the literal AC ID):

- **opsx-cli** (3): unified-subcommand-dispatch, hard-cutover-no-legacy-entrypoints,
  model-config-write-surface → `tests/opsx-cli/test_opsx_cli.sh` + tasks.md.
- **opsx-loop-kickoff** (6): argument-parsing-preserves-full-input,
  stall-detection-stops-the-loop, model-config-subcommand, single-command-guaranteed-loop,
  opsx-gate-is-the-deterministic-judge, loop-exports-resolved-role-models →
  `helpers.test.ts` / `helpers.ts` / `index.ts` + tasks.md.
- **opsx-gate-enforcement** (7) → `tests/opsx-gate/test_opsx_gate.sh` + `test_author_marker.sh`.
- **opsx-model-config** (4) → `tests/opsx-models/test_opsx_models.sh` + `test_author_marker.sh`.
- **opsx-workflow-schema** (4), **opsx-loop-orchestration** (2),
  **opsx-skill-integration** (2) — rename-only MODIFIED deltas (behavior unchanged); cited in
  tasks.md (migration tasks 3.1/4.1) and exercised by the existing gate/models behavior suites.

Result: **28/28 forward-mapped, 0 missing.**

## Independent verification run (this checkout)

| Suite | Result |
|---|---|
| `tests/opsx-models/test_opsx_models.sh` (→ `opsx models`) | 25 passed, 0 failed |
| `tests/opsx-gate/test_opsx_gate.sh` (→ `opsx gate`) | 26 passed, 0 failed |
| `tests/opsx-gate/test_author_marker.sh` | 4 passed, 0 failed |
| `tests/opsx-cli/test_opsx_cli.sh` (dispatch + write surface) | 17 passed, 0 failed |
| `bun test helpers.test.ts` (opsx-loop) | 29 pass |
| `bun build index.ts` transpile | clean |
| `bun test helpers.test.ts` (goal, untouched) | 32 pass |
| `bash -n dot_local/bin/executable_opsx` | clean |
| token-level legacy-executable scan (caller paths) | clean (no stale `opsx-gate`/`opsx-models`/`opsx-loop`-driver invocations) |
| `openspec validate consolidate-opsx-cli --strict` | valid |

Total: **133 tests green** (72 shell + 29 + 32) plus transpile, syntax, scan, validate. Post-impl
code-review: **PASS, adversarial-multimodel** (opus-4-8 + gpt-5.5, 3 blind rounds, 0 P0/0 P1).
