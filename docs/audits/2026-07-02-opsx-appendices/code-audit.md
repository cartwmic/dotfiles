# opsx workflow implementation audit

Date: 2026-07-02
Scope: `dot_local/bin/executable_opsx`, `dot_pi/agent/extensions/opsx-loop/`, and `tests/opsx-{gate,models,cli}/`.
Mode: read-only audit of implementation; no production code changes made.

## Inputs checked

- `plan.md`: **missing** at repo root (`/Users/cartwmic/.local/share/chezmoi/plan.md` not found).
- `progress.md`: read; only states research brief started.
- Specs consulted for expected behavior:
  - `openspec/specs/opsx-loop-kickoff/spec.md`
  - `openspec/specs/opsx-loop-orchestration/spec.md`
  - `openspec/specs/opsx-gate-enforcement/spec.md`
  - `openspec/specs/opsx-cli/spec.md`
  - `dot_local/share/agent-harness/canonical/skills/openspec-apply-change/references/opsx-superpowers-mode.md`

## Validation run

All current tests pass:

- `bash tests/opsx-cli/test_opsx_cli.sh` → 17 passed, 0 failed
- `bash tests/opsx-models/test_opsx_models.sh` → 25 passed, 0 failed
- `bash tests/opsx-gate/test_opsx_gate.sh` → 52 passed, 0 failed
- `bun test dot_pi/agent/extensions/opsx-loop/helpers.test.ts` → 45 passed, 0 failed

Passing tests do not cover several high-risk integration paths below.

## Executive summary

Implementation mostly matches deterministic gate and loop intent for same-tree, happy-path usage. Exit-code contract is correct in tested cases: `opsx gate` exit 0 means green; non-zero means loop continues/stops by budget/stall.

Main risk is worktree integration. `opsx gate --worktree` uses the worktree for validation cwd and HEAD freshness, but still reads required artifacts, task state, and verdict files from the integration checkout. That conflicts with the documented apply workflow where work happens in the worktree. Result: worktree-required changes can stall or fail even after the worktree has the updated `tasks.md`, `verify.md`, `code-review.md`, or `doneness.md`.

Second main risk is loop environment contamination: the pi extension exports model env vars into global `process.env` but never clears old values, so one loop can affect later loops and gate behavior.

## Findings by severity

### P1 — `opsx gate --worktree` reads change artifacts from root, not from the worktree

**Evidence**

- `dot_local/bin/executable_opsx:381-384` sets `ROOT` from `OPSX_ROOT`/cwd and `CDIR="$ROOT/openspec/changes/$CHANGE"`.
- Required artifact and task checks read `CDIR`: `dot_local/bin/executable_opsx:436-463`.
- Verify/code-review/doneness files read `CDIR`: `dot_local/bin/executable_opsx:597`, `607`, `673`.
- `--worktree` affects only implementation HEAD / validation cwd / freshness repo:
  - `dot_local/bin/executable_opsx:500-511` computes `IMPL_HEAD` from `WT_PATH` when present.
  - `dot_local/bin/executable_opsx:533-540` runs validation command in `WT_PATH` when present.
  - `dot_local/bin/executable_opsx:588` sets `GW` to `WT_PATH` for `git rev-parse` freshness.
- Apply workflow says worktree lifecycle writes/uses change artifacts in the worktree:
  - `dot_local/share/agent-harness/canonical/skills/openspec-apply-change/references/opsx-superpowers-mode.md`: worktree creation and per-task workflow; task completion edits `tasks.md`, post-apply produces `verify.md`/`code-review.md`, and completion gate is `opsx gate <name> --worktree <worktree-path>`.

**Impact**

For `worktree-required` changes, worker may update `openspec/changes/<change>/tasks.md`, `verify.md`, `code-review.md`, and `doneness.md` inside the worktree, while `opsx gate --worktree` still reads the stale integration-branch copies. Gate can fail tasks/verdicts forever despite the worktree being correct. Conversely, stale root artifacts can be mixed with worktree HEAD, producing inconsistent freshness checks and validation context.

`OPSX_CHANGE_DIR` exported to validations also points at root (`dot_local/bin/executable_opsx:538`) while validation cwd is worktree, so manifest gates that inspect `$OPSX_CHANGE_DIR` may inspect stale artifacts.

**Test gap**

`tests/opsx-gate/test_opsx_gate.sh` only checks missing Worktree Path fails (`lines 194-199`) and same-tree verdict freshness. No test creates a real `opsx/<change>` worktree where root `tasks.md` is stale but worktree `tasks.md` is complete, nor worktree-only `verify.md`/`code-review.md`/`doneness.md`.

**Suggested fix**

When a valid worktree is selected, gate should consistently use a worktree change dir for artifact/task/verdict reads, e.g. `ART_ROOT="$WT_PATH"` after worktree validation and `CDIR="$ART_ROOT/openspec/changes/$CHANGE"` for post-worktree checks, or explicitly define which artifacts remain integration-branch-owned and enforce sync. Also export `OPSX_CHANGE_DIR` matching that chosen artifact source.

---

### P1 — Missing option values can hang option parsers forever

**Evidence**

- `opsx gate --worktree` parser uses `WORKTREE_ARG="${2:-}"; shift 2` without checking `$# >= 2`: `dot_local/bin/executable_opsx:371-374`.
- `opsx models` role mode uses `--change) CHANGE="${2:-}"; shift 2`: `dot_local/bin/executable_opsx:52-55`.
- `opsx models` verb mode uses `--layer) LAYER="${2:-}"; shift 2` and `--change) CHANGE="${2:-}"; shift 2`: `dot_local/bin/executable_opsx:63-68`.
- Reproduced with timeout:
  - `timeout 2s dot_local/bin/executable_opsx gate foo --worktree` exited `124` (timed out).
  - `timeout 2s dot_local/bin/executable_opsx models author --change` exited `124` (timed out).

**Impact**

Malformed CLI input can spin the shell process until killed. In the pi extension, a bad invocation path or generated command with a missing option value can wedge the judge subprocess and the active loop.

**Test gap**

No CLI/gate/models test covers missing option arguments. Existing tests cover missing subcommand and unknown role/options, but not dangling `--worktree`, `--change`, or `--layer`.

**Suggested fix**

Before `shift 2`, require a non-empty second argument or exit 2 with usage. Example pattern: `--worktree) [ $# -ge 2 ] && [ -n "$2" ] || { echo ...; exit 2; }; WORKTREE_ARG="$2"; shift 2 ;;`.

---

### P1 — opsx-loop model env exports leak across loops

**Evidence**

- `exportModelEnv()` only sets keys returned by `buildModelEnv`; it never deletes stale `OPSX_AUTHOR_MODEL`, `OPSX_REVIEW_MODELS`, `OPSX_IMPL_MODEL`, or `OPSX_AUTHOR_IN_SESSION`: `dot_pi/agent/extensions/opsx-loop/index.ts:117-125`.
- Resolver precedence treats env as the highest layer: `dot_local/bin/executable_opsx:245-255`.
- Gate author-marker enforcement uses `opsx_models author --json` and sees env source as configured: `dot_local/bin/executable_opsx:473-488`.
- Loop kickoff exports on explicit change start: `dot_pi/agent/extensions/opsx-loop/index.ts:371-384`; goal adoption exports at `452-457`.

**Impact**

Start loop A with configured `OPSX_AUTHOR_MODEL`; then start loop B with no configured author. Since old env remains in the pi process, `opsx models author --json --change B` resolves source `env`, not `unset`. Worker turns and `opsx gate` subprocesses inherit stale model config. This can force author-marker checks on unrelated changes, dispatch wrong models, and make model resolution differ from repo config.

**Test gap**

Helper tests validate `buildModelEnv()` output but do not test extension process-level cleanup or sequential loop starts with different model configs.

**Suggested fix**

Before applying new exports, delete the known `OPSX_*` role keys from `process.env`, then set newly resolved keys. Consider scoping env per injected worker turn if pi API supports it rather than mutating global process env.

---

### P1 — No timeout for gate/validation subprocesses can wedge loop indefinitely

**Evidence**

- Pi extension `runGate()` spawns `opsx gate` with no timeout: `dot_pi/agent/extensions/opsx-loop/index.ts:146-160`.
- Gate `run_in_impl()` executes manifest and `OPSX_VALIDATE` commands with `bash -c` and no timeout: `dot_local/bin/executable_opsx:533-540`, called from `555-559` and `565-570`.
- Bash fallback loop calls `gate` and pipes into `$AGENT_CMD` with no timeout: `dot_local/bin/executable_opsx:792-810`.

**Impact**

A hung manifest gate, hung `OPSX_VALIDATE`, or stuck `opsx gate` process leaves the pi loop in `evaluating=true` awaiting a promise that never resolves. Budget and stall guards only run after gate returns, so they cannot recover.

**Test gap**

No tests cover a hanging manifest gate or hanging `opsx gate` subprocess.

**Suggested fix**

Add bounded timeouts around `opsx gate` in the extension and around each validation command in `opsx gate` (configurable default). On timeout, emit `GATE-FAIL validation-<id>` or a judge failure verdict and continue/stop via normal loop logic.

---

### P2 — Loop budget parsing accepts malformed numeric strings and fallback loop differs from extension

**Evidence**

- Extension parser matches leading digits but does not require the whole value to be numeric: `dot_pi/agent/extensions/opsx-loop/helpers.ts:255-267`, especially regex at `261` (`(\d+)` not anchored to end). `loop_max_iterations: 80junk` parses as `80`, though spec says unparseable should be unset.
- Bash fallback strips all non-digits: `dot_local/bin/executable_opsx:783-789`. `loop_max_iterations: -1` becomes `1`; `abc80` becomes `80`.
- Fallback applies default `40` when absent/unparseable: `dot_local/bin/executable_opsx:783-790`, while extension/spec says absent or unparseable means unbounded/no built-in numeric default.

**Impact**

Budget behavior differs between pi extension and `opsx loop` fallback. Malformed front matter can unexpectedly shrink, expand, or default the loop budget.

**Test gap**

`helpers.test.ts:88-105` covers valid number, absent, no front matter, `0`, `abc`, and empty input. It does not cover suffix/prefix garbage, negative numbers, quoted values, or parity with bash fallback.

**Suggested fix**

Use one shared strict parser semantics: only positive integer scalar with optional surrounding whitespace is valid. Anchor regex to end in TypeScript. In bash, do not strip non-digits; reject anything not matching `^[[:space:]]*loop_max_iterations:[[:space:]]*[1-9][0-9]*[[:space:]]*$`. Align fallback default with current spec or document fallback exception.

---

### P2 — Goal/conversation kickoff has no way to enforce a configured pre-change budget

**Evidence**

- Goal mode initializes `maxTurns: undefined`: `dot_pi/agent/extensions/opsx-loop/index.ts:343-349`.
- Distilling phase checks `if (session.maxTurns !== undefined && session.turns >= session.maxTurns)`: `dot_pi/agent/extensions/opsx-loop/index.ts:421-424`.
- `maxTurns` is only populated after a change is detected/adopted: `dot_pi/agent/extensions/opsx-loop/index.ts:452-456`.
- Spec has a scenario for "No change created within a configured budget stops the loop" in `openspec/specs/opsx-loop-kickoff/spec.md`.

**Impact**

Before a new change exists, `maxTurns` is always undefined, so the budget-exhaustion branch in distilling mode is dead code. Only the `lastDirs` stall guard bounds pre-change looping. If the intended design requires a user/session configured distill budget, it is not implemented.

**Test gap**

No extension integration test simulates goal mode with a budget. Helper tests only cover argument parsing and budget parser.

**Suggested fix**

Either remove the unreachable configured-budget claim for pre-change mode and rely solely on `lastDirs`, or add an explicit budget source for goal/conversation mode (command arg, extension config, or session setting).

---

### P2 — Worktree lifecycle creation/reuse/cleanup is not owned by audited runtime

**Evidence**

- `dot_pi/agent/extensions/opsx-loop/index.ts` only reads `Worktree Path` from `review.md` and checks it is a git worktree: `165-174`, re-resolved per turn at `462-468`.
- `dot_local/bin/executable_opsx` gate validates worktree path/branch only after cheap checks and only for exact `worktree-required`: `513-525`.
- No audited component calls `git worktree add`, handles branch reuse/base preservation, or cleanup. `grep` in audited runtime finds no lifecycle commands beyond validation.
- The apply reference documents lifecycle requirements: creation failure aborts, stale branch reuse preserves `Diff Base SHA`, cleanup after archive.

**Impact**

Creation failure, stale branch reuse, and cleanup are delegated to agent skill instructions, not enforced by deterministic runtime. Autonomous loops can proceed only insofar as the agent follows prose. Known past review gap remains in the audited components.

**Test gap**

No tests cover worktree creation failure, branch `opsx/<change>` already existing with stale base, invalid recorded base, or cleanup after archive/gate failure.

**Suggested fix**

If runtime is meant to own lifecycle, add explicit `opsx worktree ensure` / `opsx archive` lifecycle commands or gate checks for `Diff Base SHA` ancestry before implementation. If lifecycle intentionally remains skill-owned, document that the runtime only validates an already-recorded worktree and add tests around branch/base validation.

---

### P2 — `/opsx-loop models` wrapper may break project root discovery from subdirectories

**Evidence**

- `runModels()` forces `OPSX_ROOT: cwd`: `dot_pi/agent/extensions/opsx-loop/index.ts:220-225`.
- `opsx models` rejects `OPSX_ROOT` unless `$OPSX_ROOT/openspec` exists: `dot_local/bin/executable_opsx:78-82`.
- If `ctx.cwd` is a subdirectory of the repo rather than repo root, normal ancestor discovery would work, but forced `OPSX_ROOT=ctx.cwd` disables it and errors.

**Impact**

`/opsx-loop models set ... --layer project` can fail or target incorrectly when pi's active cwd is a repo subdirectory. Requirement says wrapper should target the active repo; this implementation assumes `ctx.cwd` is always the repo root.

**Test gap**

Tests cover CLI project-layer writes with `OPSX_ROOT` set to the exact project root, not the extension wrapper from a subdirectory.

**Suggested fix**

Resolve repo root before calling `opsx models` (`git -C cwd rev-parse --show-toplevel`) and pass that as cwd/`OPSX_ROOT`, or omit `OPSX_ROOT` and let `opsx models` ancestor discovery run.

---

### P2 — Worktree mode and other mode values are not validated for malformed values

**Evidence**

- Gate reads modes from front matter: `dot_local/bin/executable_opsx:417-421`.
- Worktree branch/path validation only runs when `WORKTREE_MODE` exactly equals `worktree-required`: `dot_local/bin/executable_opsx:513-525`.
- Verify/code-review enforcement only runs on exact strings (`retained-required`, `gating-required`): `597-618`.
- `doneness_mode` defaults only when absent; any value other than `waived` behaves as required in practice: `672`, `708-740`.

**Impact**

Typos like `worktree_requred` silently disable worktree validation instead of failing closed. Similar typos in verify/code-review modes can weaken enforcement.

**Test gap**

No tests cover malformed mode values.

**Suggested fix**

Validate mode fields against allowed enumerations after front-matter read. Fail closed with `GATE-FAIL mode` for unknown values on fields that affect enforcement.

---

### P3 — `opsx models list` does not check `jq` availability

**Evidence**

- Verb mode checks `yq` only: `dot_local/bin/executable_opsx:137-139`.
- `list` uses `jq` to parse each role output: `dot_local/bin/executable_opsx:140-145`.

**Impact**

If `jq` is missing, list silently prints `(unset)`/`unset`-style fallbacks or incomplete data rather than a clear dependency error. Tests require jq up front (`tests/opsx-cli/test_opsx_cli.sh:15-16`), so the degraded behavior is untested.

**Suggested fix**

Check `command -v jq` before `list`, or format list without jq.

---

## Correct / good implementation notes

- Gate exit-code contract is implemented and tested: `opsx gate` emits `GATE-PASS` and exits 0 only after required checks pass (`dot_local/bin/executable_opsx:746-750`); tests cover pass/fail at `tests/opsx-gate/test_opsx_gate.sh:63-66`.
- Cheap-before-expensive behavior is implemented (`dot_local/bin/executable_opsx:490-494`) and tested (`tests/opsx-gate/test_opsx_gate.sh:80-92`).
- `worktree-required` with missing/invalid path is a hard fail when reached (`dot_local/bin/executable_opsx:513-525`) and missing-path test exists (`tests/opsx-gate/test_opsx_gate.sh:194-199`).
- Green-state kickoff short-circuits correctly: extension pre-runs gate and does not arm loop on met verdict (`dot_pi/agent/extensions/opsx-loop/index.ts:360-369`).
- Re-entrancy guard exists: active evaluation ignores nested `agent_end` (`dot_pi/agent/extensions/opsx-loop/index.ts:392-393`).
- Budget check in explicit-change mode is not off by one for configured budgets: turns increment after each worker turn (`411`), and red gate with `turns >= maxTurns` stops before injecting another turn (`478-482`).
- Stall detection covers normalized failure keys, worktree changes, content/HEAD progress, and special doneness gap-set ratchet (`dot_pi/agent/extensions/opsx-loop/index.ts:485-526`; helper tests at `helpers.test.ts:12-65`, `163-190`).
- `lastDirs` guard prevents unbounded goal/conversation distill loops when no new change dir appears (`dot_pi/agent/extensions/opsx-loop/index.ts:431-449`).
- CLI model write surface has good atomic-write coverage and tests for failed writes leaving files unchanged (`tests/opsx-cli/test_opsx_cli.sh:126-142`).

## Highest-value test additions

1. Worktree artifact source integration test: create `opsx/<change>` worktree, leave root `tasks.md` unchecked, mark worktree `tasks.md` checked, run `opsx gate --worktree`; expected behavior should be explicit.
2. Worktree verdict test: `code-review.md` / `verify.md` / `doneness.md` only or newer in worktree; ensure gate reads the intended copy.
3. Missing option value tests for `opsx gate --worktree`, `opsx models author --change`, and `opsx models set author x --layer` should exit 2 quickly.
4. Sequential loop model-env test: start loop with configured author model, then start one without; ensure old `OPSX_AUTHOR_MODEL` is absent.
5. Hanging manifest command timeout test.
6. Budget parser parity tests for `80junk`, `abc80`, `-1`, quoted numbers, and absent value across extension and bash fallback.
7. Goal-mode distill budget integration test or removal of dead budget branch.
8. Worktree lifecycle tests for creation failure, stale `opsx/<change>` branch reuse, invalid/missing `Diff Base SHA`, and cleanup/archive handoff.
9. Malformed front-matter mode tests for `worktree_mode`, `verification_mode`, `code_review_mode`, `validation_source_mode`, and `doneness_mode`.
