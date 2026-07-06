<!-- authored: in-session -->

# Execution Plan

## Plan step 1: Build isolated TUI harness

- **Covers:** T1.1, T1.2
- **Pre-conditions:**
  - Pi CLI and tmux are available locally.
  - Existing `pi-tui-scenario-tests` skill examples are used as reference, not as a runtime dependency.
- **Action:**
  1. Create `tests/opsx-tui/SCENARIOS.md` documenting default and optional scenarios with AC IDs `opsx-loop.scenario-harness-is-isolated-and-signal-driven` and `opsx-loop.tui-scenarios-exercise-user-visible-slash-commands`.
  2. Add `tests/opsx-tui/scripts/scenario-lib.sh` with unique tmux socket setup, temp repo/HOME setup, pane capture, regex/log-counter waits, and cleanup traps.
  3. Add fake `opsx` and fake-provider fixtures under `tests/opsx-tui/fixtures` or generated temp-bin helpers.
  4. Add `run-all-scenarios.sh` with per-scenario timeout, summary output, and opt-in filtering.
  5. Run a harness self-check scenario and commit.
- **Verification:**
  - `bash -n tests/opsx-tui/scripts/*.sh`
  - A minimal scenario launches and tears down its private tmux server.
- **Rollback:**
  - Remove `tests/opsx-tui/**` files from the worktree branch.

## Plan step 2: Add command visibility scenarios

- **Covers:** T2.1, T2.2
- **Pre-conditions:**
  - Harness can launch Pi with `-ne -e dot_pi/agent/extensions/opsx-loop` or an equivalent source-extension path.
  - Fake `opsx` logs argv/cwd/env.
- **Action:**
  1. Add status/bare/clear scenarios citing AC `opsx-loop.tui-scenarios-exercise-user-visible-slash-commands`.
  2. Add models-list/models-set scenario asserting full argv preservation and pane-visible fake CLI output.
  3. Fix `dot_pi/agent/extensions/opsx-loop/**` only if the real TUI exposes a command visibility defect.
  4. Run command scenarios until passing.
  5. Commit scenario files and any minimal extension fix.
- **Verification:**
  - `bash tests/opsx-tui/scripts/run-all-scenarios.sh` with command scenario filter.
  - `bun test dot_pi/agent/extensions/opsx-loop/`
- **Rollback:**
  - Revert the step commit; temp tmux servers are killed by cleanup traps.

## Plan step 3: Add loop-state scenarios

- **Covers:** T3.1, T3.2
- **Pre-conditions:**
  - Fake `opsx gate` can return scripted red/green sequences.
  - Fake provider can emit a deterministic short turn when an `agent_end` path must be exercised.
- **Action:**
  1. Add already-green scenario citing AC `opsx-loop.tui-scenarios-exercise-deterministic-loop-states`.
  2. Add red-arm-status-clear scenario asserting arm, status, clear, and no further continuation.
  3. Add goal-distill scenario asserting full multi-word goal text and paused intent-confirmation landing.
  4. Add loop-hold/re-arm scenario asserting hold reason visibility and re-arm clearing semantics.
  5. Commit scenario files and any minimal extension fix.
- **Verification:**
  - `bash tests/opsx-tui/scripts/run-all-scenarios.sh` with loop scenario filter.
  - `bun test dot_pi/agent/extensions/opsx-loop/`
- **Rollback:**
  - Revert the step commit; remove temp dirs captured in scenario logs if cleanup failed.

## Plan step 4: Integrate validation evidence

- **Covers:** T4.1, T4.2
- **Pre-conditions:**
  - Default scenario suite passes locally with fake provider/fake `opsx`.
- **Action:**
  1. Document optional real-model smoke and required opt-in env flag.
  2. Add retained validation notes or gate/test docs so maintainers know when to run the TUI suite.
  3. Run canonical validators and the new scenario suite.
  4. Record verification evidence in `verify.md` if the gate requests it.
  5. Commit final validation/doc updates.
- **Verification:**
  - `bash -n dot_local/bin/executable_opsx`
  - `bun test dot_pi/agent/extensions/opsx-loop/`
  - `bash tests/opsx-cli/test_opsx_cli.sh`
  - `bash tests/opsx-gate/test_opsx_gate.sh`
  - `bash tests/opsx-gate/test_author_marker.sh`
  - `bash tests/opsx-models/test_opsx_models.sh`
  - `bash tests/opsx-review-convergence/test_review_convergence_surfaces.sh`
  - `bash tests/opsx-tui/scripts/run-all-scenarios.sh`
  - `openspec validate add-opsx-loop-tui-scenarios --strict`
- **Rollback:**
  - Revert validation/doc commit; preserve scenario logs for diagnosis.

## Completion Verification

- `opsx gate add-opsx-loop-tui-scenarios --worktree <recorded-worktree-path>` exits 0.
- `bash tests/opsx-tui/scripts/run-all-scenarios.sh` passes in default fake-provider mode.
- Tests contain literal AC IDs:
  - `opsx-loop.tui-scenarios-exercise-user-visible-slash-commands`
  - `opsx-loop.tui-scenarios-exercise-deterministic-loop-states`
  - `opsx-loop.scenario-harness-is-isolated-and-signal-driven`

## Manual Adjustments

- Plain Scale M: no `design.md` because the approach follows the frozen intent without a non-trivial architecture trade-off needing a separate design artifact; deterministic analyze notes are recorded in `proposal.md`.
- No user questions were asked during proposal because the frozen intent already resolved default fake-provider vs optional real-model smoke and requested autonomous drive-to-green.
