# Verify

**Generated:** 2026-07-14 by fresh blind read-only verifier
**Change:** `preserve-opsx-loop-across-native-retries`
**Diff base:** `a5cc8de5040107e121a199caf845358a395b98d0`
**Verified range:** `a5cc8de5040107e121a199caf845358a395b98d0..b4dd9763710176710e1c6f4b9850e0c969dd8893`
**Range ancestry:** base exists as commit; `git merge-base` equals base; 12 commits in range
**Acceptance criterion:** `opsx-loop.interrupt-or-error-stops-the-loop`
**Tree state:** clean; `git diff --check` passed

Input note: requested root-level `plan.md` and `progress.md` do not exist at attested path. Verification used authoritative `openspec/changes/preserve-opsx-loop-across-native-retries/plan.md`; no progress file was available. Existing retained `verify.md` finding prose was not read. Its path and machine-only credential scan remain included in changed-file audit.

## Completion Decision

**Status:** green

## Checks

| # | Check | Status | Exact evidence |
|---|---|---|---|
| 1 | Structural validation (`openspec validate --strict --json`) | pass | `openspec validate preserve-opsx-loop-across-native-retries --strict --json` exited 0; 1 item, 1 passed, 0 failed, `valid: true`, issues `[]`. |
| 2 | Task completion | pass | Deterministic count over `tasks.md`: 0 unchecked boxes; 7 checked boxes. |
| 3 | Delta vs current spec coherence | pass | Current capability has requirement `Interrupt or error stops the loop`; delta uses `## MODIFIED Requirements` and supplies full replacement requirement. It retains explicit-interrupt and goal-extension scenarios, changes only errored-attempt/final-settlement semantics, and adds clean-retry, settled-error, bounded-overflow, persistent-overflow, and stale-replacement scenarios. Strict validator reports no issue. |
| 4 | Commit hygiene | pass | 12/12 subjects are ≤72 characters (maximum 52); 12/12 have non-empty bodies beginning with `Why:`. No offender. |
| 5 | AC↔test mapping | pass | Forward: canonical AC appears literally in 13 changed test files. Reverse: all 13 changed test files contain canonical AC reference; 0 orphan, 0 exemption. Details below. |
| 6 | Constitution compliance audit | pass | All 17 changed files audited. `dot_pi/.../index.ts` uses proper chezmoi source path (I); OpenSpec files remain under ignored `openspec/` workspace (VIII); no skill, installer, mise, launchd, or Termux surface changed; goal extension unchanged; machine scan found 0 credential-pattern hits (III). Details below. |

## Check 3 detail — spec and implementation coherence

- Existing spec baseline says interruption or worker error clears loop immediately.
- Delta fully replaces requirement with attempt-versus-settlement contract: explicit abort remains immediate; `agent_end(error)` preserves exact loop; clean continuation gates once; unresolved `agent_settled` stops; overflow recovery remains one-shot; stale outcomes cannot affect replacement.
- Runtime evidence:
  - `LoopState.pendingError`: `dot_pi/agent/extensions/opsx-loop/index.ts:88`.
  - generation invalidation and pending arm: lines 397, 663, 701-702, 739.
  - top-level ownership capture/transfer: lines 823 and 830.
  - `agent_end` attempt handling: line 846; error recorded at 875; clean path clears pending outcome at 881.
  - final settlement handling: line 1032; one-shot overflow branch at 1058.
  - compaction abort classification/landing: lines 416 and 422.
- Scope remains provider-neutral: fake provider controls deterministic status/error fixtures; runtime adds no status-code table, provider fallback, timer, backoff, or extension-owned transport retry.
- `git diff --name-only` contains no goal-extension path (`GOAL_CHANGED=False`).

## Check 4 detail — commit hygiene

| Commit | Subject chars | Body | Subject |
|---|---:|---|---|
| `572b3911e4ec` | 52 | `Why:` present | `fix(opsx-loop): preserve loop through native retries` |
| `7c0ac3caf640` | 48 | `Why:` present | `test(opsx-loop): script provider status sequence` |
| `bc150192936f` | 46 | `Why:` present | `test(opsx-loop): cover native retry continuity` |
| `6e5113af42de` | 47 | `Why:` present | `test(opsx-loop): cover exhausted native retries` |
| `fd0cfa480d30` | 52 | `Why:` present | `test(opsx-loop): complete retry lifecycle validation` |
| `cee8d37b3805` | 45 | `Why:` present | `test(opsx-loop): close settled lifecycle gaps` |
| `0f1aa648b64f` | 45 | `Why:` present | `fix(opsx-loop): invalidate before re-arm gate` |
| `443676f2c26f` | 43 | `Why:` present | `test(opsx-loop): trace delayed gate fixture` |
| `81a49b653e79` | 40 | `Why:` present | `test(opsx-loop): seal green verification` |
| `a36f9752769c` | 48 | `Why:` present | `fix(opsx-loop): bind exact replacement directive` |
| `40f0972cedf6` | 43 | `Why:` present | `test(opsx-loop): refresh green verification` |
| `b4dd97637101` | 46 | `Why:` present | `fix(opsx-loop): harden arm and abort ownership` |

## Check 5 detail — AC↔test mapping (test files only)

Changed-test heuristic: path matches `(^|/)tests?/` or `\.(test|spec)\.[^.]+$`. This yields 13 files. OpenSpec artifacts, including retained `verify.md`, cannot satisfy forward coverage.

### Forward coverage

| AC ID | Literal changed-test references | Status |
|---|---|---|
| `opsx-loop.interrupt-or-error-stops-the-loop` | `tests/opsx-tui/SCENARIOS.md:29-38`; `tests/opsx-tui/fixtures/fake-openai-server.mjs:2`; `tests/opsx-tui/fixtures/fake-opsx.sh:2`; every scenario script `run-scenario-s07-native-retry.sh` through `run-scenario-s16-overflow-compact-abort.sh` at line 2 | covered |

### Reverse coverage

| Changed test file | AC reference | Status |
|---|---|---|
| `tests/opsx-tui/SCENARIOS.md` | `opsx-loop.interrupt-or-error-stops-the-loop` at lines 29-38 | referenced |
| `tests/opsx-tui/fixtures/fake-openai-server.mjs` | `opsx-loop.interrupt-or-error-stops-the-loop` at line 2 | referenced |
| `tests/opsx-tui/fixtures/fake-opsx.sh` | `opsx-loop.interrupt-or-error-stops-the-loop` at line 2 | referenced |
| `tests/opsx-tui/scripts/run-scenario-s07-native-retry.sh` | `opsx-loop.interrupt-or-error-stops-the-loop` at line 2 | referenced |
| `tests/opsx-tui/scripts/run-scenario-s08-retry-exhausted.sh` | `opsx-loop.interrupt-or-error-stops-the-loop` at line 2 | referenced |
| `tests/opsx-tui/scripts/run-scenario-s09-overflow-recovery.sh` | `opsx-loop.interrupt-or-error-stops-the-loop` at line 2 | referenced |
| `tests/opsx-tui/scripts/run-scenario-s10-overflow-persistent.sh` | `opsx-loop.interrupt-or-error-stops-the-loop` at line 2 | referenced |
| `tests/opsx-tui/scripts/run-scenario-s11-clear-during-retry.sh` | `opsx-loop.interrupt-or-error-stops-the-loop` at line 2 | referenced |
| `tests/opsx-tui/scripts/run-scenario-s12-rearm-during-retry.sh` | `opsx-loop.interrupt-or-error-stops-the-loop` at line 2 | referenced |
| `tests/opsx-tui/scripts/run-scenario-s13-prequeued-rearm.sh` | `opsx-loop.interrupt-or-error-stops-the-loop` at line 2 | referenced |
| `tests/opsx-tui/scripts/run-scenario-s14-clear-pending-arm.sh` | `opsx-loop.interrupt-or-error-stops-the-loop` at line 2 | referenced |
| `tests/opsx-tui/scripts/run-scenario-s15-duplicate-rearm.sh` | `opsx-loop.interrupt-or-error-stops-the-loop` at line 2 | referenced |
| `tests/opsx-tui/scripts/run-scenario-s16-overflow-compact-abort.sh` | `opsx-loop.interrupt-or-error-stops-the-loop` at line 2 | referenced |

**Reverse result:** 13 referenced, 0 orphan, 0 exempt.

## Check 6 detail — Constitution audit of all changed files

| Changed file | Principles checked | Status | Notes |
|---|---|---|---|
| `dot_pi/agent/extensions/opsx-loop/index.ts` | I, III | compliant | Deployed Pi extension remains in chezmoi `dot_pi/` source; no credential; no goal-extension modification. |
| `openspec/changes/preserve-opsx-loop-across-native-retries/plan.md` | III, VIII | compliant | Repo-local change artifact under ignored OpenSpec workspace. |
| `openspec/changes/preserve-opsx-loop-across-native-retries/tasks.md` | III, VIII | compliant | Repo-local task artifact; file contracts match implementation/test paths. |
| `openspec/changes/preserve-opsx-loop-across-native-retries/verify.md` | III, VIII | compliant | Repo-local retained evidence path; prior finding prose intentionally not consumed; machine-only credential scan returned 0. |
| `tests/opsx-tui/SCENARIOS.md` | III | compliant | Test documentation only; no deployment or secret. |
| `tests/opsx-tui/fixtures/fake-openai-server.mjs` | III | compliant | Loopback fake provider; no hosted credential; opt-in fixture behavior. |
| `tests/opsx-tui/fixtures/fake-opsx.sh` | III, IV | compliant | Test fixture only; writes inside scenario temp/log roots; no install-script surface. |
| `tests/opsx-tui/scripts/run-scenario-s07-native-retry.sh` | III, IV | compliant | Disposable deterministic scenario; cleanup supplied by shared trap. |
| `tests/opsx-tui/scripts/run-scenario-s08-retry-exhausted.sh` | III, IV | compliant | Disposable deterministic scenario; bounded provider count assertion. |
| `tests/opsx-tui/scripts/run-scenario-s09-overflow-recovery.sh` | III, IV | compliant | Disposable deterministic scenario; bounded recovery assertion. |
| `tests/opsx-tui/scripts/run-scenario-s10-overflow-persistent.sh` | III, IV | compliant | Disposable deterministic scenario; no third retry assertion. |
| `tests/opsx-tui/scripts/run-scenario-s11-clear-during-retry.sh` | III, IV | compliant | Disposable deterministic stale-settlement scenario. |
| `tests/opsx-tui/scripts/run-scenario-s12-rearm-during-retry.sh` | III, IV | compliant | Disposable deterministic replacement-ownership scenario. |
| `tests/opsx-tui/scripts/run-scenario-s13-prequeued-rearm.sh` | III, IV | compliant | Disposable deterministic exact-directive ownership scenario. |
| `tests/opsx-tui/scripts/run-scenario-s14-clear-pending-arm.sh` | III, IV | compliant | Disposable deterministic pending-arm cancellation scenario. |
| `tests/opsx-tui/scripts/run-scenario-s15-duplicate-rearm.sh` | III, IV | compliant | Disposable deterministic generation-identity scenario. |
| `tests/opsx-tui/scripts/run-scenario-s16-overflow-compact-abort.sh` | III, IV | compliant | Disposable deterministic compaction-abort scenario. |

**Audit coverage:** 17 of 17 changed files = 100%. Because 10 < N ≤ 50, every changed file was audited and this coverage note is emitted. `.chezmoiignore:14` still contains `openspec/`. Principles II, V, VI, VII, IX, and X are not activated by this diff.

## Validation evidence

### Focused tests

- `bun test dot_pi/agent/extensions/opsx-loop/helpers.test.ts` — exit 0: **94 pass, 0 fail, 221 expect() calls**, 1 file.
- Shell/fixture syntax — exit 0: `bash -n` for s07-s16 plus `fake-opsx.sh`; `node --check fake-openai-server.mjs`; **12 files passed**.

### Full real-Pi TUI from disposable HEAD archive

Archive command used `git archive --format=tar HEAD` and extracted into:

`/tmp/preserve-opsx-loop-round5.HOLjHT`

Runner used archive-contained extension and tests, not working-tree files:

`bash /tmp/preserve-opsx-loop-round5.HOLjHT/tests/opsx-tui/scripts/run-all-scenarios.sh`

Result: exit 0, **17 passed, 0 failed, 0 timeout** (`s00` through `s16`). Default s06 skip path was followed by explicit opt-in execution from same archive:

`OPSX_TUI_ENABLE_INTERRUPT=1 OPSX_TUI_SCENARIO_FILTER='^s06-interrupt-optional$' .../run-all-scenarios.sh`

Result: exit 0, **1 passed, 0 failed, 0 timeout**; log: `PASS: escape interrupt stops loop`.

Focused lifecycle signals from archive logs:

- s07: native retry reaches gate; gate count kickoff + one clean completion; no extra provider turn.
- s08: exhausted native retries produce one final stop; failed attempts do not gate; no opsx retry.
- s09-s10: one overflow recovery succeeds; persistent second overflow stops without third request.
- s11-s15: clear/re-arm/prequeued/duplicate/pending-arm stale ownership cannot mutate or gate replacement.
- s16: Escape during overflow compaction stops loop and injects no recovery turn.

### Aggregate opsx gate note

`opsx gate preserve-opsx-loop-across-native-retries --worktree /Users/cartwmic/.local/share/chezmoi--opsx-preserve-opsx-loop-across-native-retries` exited 1 with:

`GATE-FAIL code-review 1 code-review.md absent (Code Review Mode gating-required)`

This does not fail any of verify template's six checks and is expected for this read-only blind-review stage: this report does not create `code-review.md`. Aggregate archive workflow remains blocked until reviewer evidence is consumed into required artifact.

## Summary

- Pass count: **6/6**
- Decision: **green**
- Verify hard-gate: **READY**
- Aggregate opsx archive gate: **BLOCKED pending required `code-review.md`**
- Implementation findings: none

## Verification Verdict

**Verification Verdict: pass — P0: 0, P1: 0, P2: 0, P3: 0.**
