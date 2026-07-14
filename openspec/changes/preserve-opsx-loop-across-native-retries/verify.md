# Verify

**Generated:** 2026-07-14 by OpenAI review-and-fix subagent / fresh blind verification
**Change:** preserve-opsx-loop-across-native-retries
**Diff Base SHA:** `a5cc8de5040107e121a199caf845358a395b98d0`
**Reviewed Range:** `a5cc8de5040107e121a199caf845358a395b98d0..443676f2c26fca3697b1460091ed3941f2eddf87`
**Acceptance Criterion:** `opsx-loop.interrupt-or-error-stops-the-loop`
**Changed Files:** 12 (`10 < N <= 50`; all changed files audited)

## Completion Decision

**Status:** green

## Checks

| # | Check | Status | Details |
|---|---|---|---|
| 1 | Structural validation (`openspec validate --strict --json`) | pass | Exact command exited 0. JSON reported one item, one passed, zero failed, `valid: true`, and `issues: []`. |
| 2 | Task completion (zero `- [ ]` in tasks.md) | pass | Exact grep reported `unchecked=0`; all seven tasks are checked. |
| 3 | Delta vs current spec coherence | pass | `openspec show ... --json --deltas-only` reported one `MODIFIED` delta for `opsx-loop`. Full replacement retains explicit-interrupt and goal-independence scenarios and coherently adds attempt-vs-settlement, clean retry, final error, bounded overflow, and stale-owner behavior. Runtime and s07-s12 implement those scenarios. Stable current spec is correctly unchanged before archive. Goal extension is unchanged. |
| 4 | Commit hygiene (subject ≤72; body explains why) | pass | Eight commits reviewed. Subject lengths: 52, 48, 46, 47, 52, 45, 45, 43. Every body has an explanatory `Why:` paragraph. Offending commits: none. |
| 5 | AC↔test mapping (canonical IDs) | pass | Forward: sole AC appears in nine changed test-path files. Reverse: all nine changed test-path files contain that AC; zero orphans and zero exemptions. |
| 6 | Constitution compliance audit (sampling) | pass | All 12 changed files audited. Runtime source remains in proper chezmoi `dot_pi/` path; OpenSpec artifacts remain under non-deployed `openspec/`; no skill, install-task, launchd, Termux, memory-promotion, goal-extension, or secret-bearing surface changed. Secret-pattern scan found zero matches. |

## Exact command evidence

### Attestation and range

```text
$ git rev-parse HEAD
443676f2c26fca3697b1460091ed3941f2eddf87
$ git rev-parse --show-toplevel
/Users/cartwmic/.local/share/chezmoi--opsx-preserve-opsx-loop-across-native-retries
$ git diff --numstat a5cc8de5040107e121a199caf845358a395b98d0..HEAD | awk 'END {print NR}'
12
$ git status --porcelain=v1 --untracked-files=all && git diff --exit-code && git diff --cached --exit-code
<no output; exit 0>
```

Changed-file enumeration:

```text
$ git diff --name-status a5cc8de5040107e121a199caf845358a395b98d0..HEAD
M  dot_pi/agent/extensions/opsx-loop/index.ts
M  openspec/changes/preserve-opsx-loop-across-native-retries/plan.md
M  openspec/changes/preserve-opsx-loop-across-native-retries/tasks.md
M  tests/opsx-tui/SCENARIOS.md
M  tests/opsx-tui/fixtures/fake-openai-server.mjs
M  tests/opsx-tui/fixtures/fake-opsx.sh
A  tests/opsx-tui/scripts/run-scenario-s07-native-retry.sh
A  tests/opsx-tui/scripts/run-scenario-s08-retry-exhausted.sh
A  tests/opsx-tui/scripts/run-scenario-s09-overflow-recovery.sh
A  tests/opsx-tui/scripts/run-scenario-s10-overflow-persistent.sh
A  tests/opsx-tui/scripts/run-scenario-s11-clear-during-retry.sh
A  tests/opsx-tui/scripts/run-scenario-s12-rearm-during-retry.sh
```

### Check 1 — structural validation

```text
$ openspec validate preserve-opsx-loop-across-native-retries --strict --json
{
  "items": [{
    "id": "preserve-opsx-loop-across-native-retries",
    "type": "change",
    "valid": true,
    "issues": [],
    "durationMs": 1
  }],
  "summary": {
    "totals": { "items": 1, "passed": 1, "failed": 0 },
    "byType": { "change": { "items": 1, "passed": 1, "failed": 0 } }
  },
  "version": "1.0"
}
```

### Check 2 — task completion

```text
$ grep -n -- '- \[ \]' openspec/changes/preserve-opsx-loop-across-native-retries/tasks.md || true; printf 'unchecked='; grep -c -- '- \[ \]' openspec/changes/preserve-opsx-loop-across-native-retries/tasks.md || true
unchecked=0
```

### Check 3 — delta coherence

```text
$ openspec show preserve-opsx-loop-across-native-retries --json --deltas-only
Warning: Ignoring flags not applicable to change: scenarios
{
  "id": "preserve-opsx-loop-across-native-retries",
  "title": "preserve-opsx-loop-across-native-retries",
  "deltaCount": 1,
  "deltas": [{
    "spec": "opsx-loop",
    "operation": "MODIFIED",
    "description": "Modify requirement: WHILE an opsx loop is active, THE extension SHALL stop immediately for an explicit user interrupt, SHALL preserve the same active loop across Pi-managed continuation after an errored low-level worker attempt, and SHALL stop visibly only when an error remains unresolved after Pi reports the agent settled. THE extension MUST NOT treat a failed low-level attempt as loop progress or start an independent provider retry."
  }]
}
$ git diff --exit-code a5cc8de5040107e121a199caf845358a395b98d0..HEAD -- openspec/specs/opsx-loop/spec.md
<no output; exit 0>
$ git diff --exit-code a5cc8de5040107e121a199caf845358a395b98d0..HEAD -- dot_pi/agent/extensions/goal
<no output; exit 0>
```

Behavioral validation ran from an exported current-HEAD snapshot at `/tmp/preserve-opsx-loop-head.066QCb`, keeping tracked repository tree and index clean:

```text
$ bun test dot_pi/agent/extensions/opsx-loop/helpers.test.ts
94 pass
0 fail
221 expect() calls
Ran 94 tests across 1 file.
$ bash tests/opsx-tui/scripts/run-all-scenarios.sh
s00-status-clear             PASS
s01-models                   PASS
s02-green-change             PASS
s03-red-arm-clear            PASS
s04-goal-distill             PASS
s05-hold-rearm               PASS
s06-interrupt-optional       PASS
s07-native-retry             PASS
s08-retry-exhausted          PASS
s09-overflow-recovery        PASS
s10-overflow-persistent      PASS
s11-clear-during-retry       PASS
s12-rearm-during-retry       PASS

Passed: 13  Failed: 0  Timeout: 0
$ OPSX_TUI_ENABLE_INTERRUPT=1 OPSX_TUI_SCENARIO_FILTER=s06 bash tests/opsx-tui/scripts/run-all-scenarios.sh
s06-interrupt-optional       PASS

Passed: 1  Failed: 0  Timeout: 0
$ bash -n <six new scenario scripts and fake-opsx.sh>
bash -n: 7/7 pass
$ git diff --check a5cc8de5040107e121a199caf845358a395b98d0..HEAD
diff_check_rc=0
```

### Check 4 — commit hygiene

```text
$ for sha in $(git rev-list --reverse a5cc8de5040107e121a199caf845358a395b98d0..HEAD); do subject=$(git show -s --format=%s "$sha"); body=$(git show -s --format=%b "$sha"); printf '%s subject_chars=%s why_body=%s\n' "$sha" "${#subject}" "$(printf '%s' "$body" | grep -q '^Why:' && echo yes || echo no)"; done
572b3911e4ec44145b37e0ce17ad7d311035e20d subject_chars=52 why_body=yes
7c0ac3caf640a87b2044c0eb9f4948c30de3a093 subject_chars=48 why_body=yes
bc150192936fad6f8d9784f740b014b8a47a957e subject_chars=46 why_body=yes
6e5113af42dee8c884f0435ea9e1c8765494efca subject_chars=47 why_body=yes
fd0cfa480d308c2db1e40e8fda0ed8eb0126b7ad subject_chars=52 why_body=yes
cee8d37b3805d1ee04a73afebcf581750daa94d8 subject_chars=45 why_body=yes
0f1aa648b64f713b74ef285b2f51c3c5100f543a subject_chars=45 why_body=yes
443676f2c26fca3697b1460091ed3941f2eddf87 subject_chars=43 why_body=yes
```

`git log --reverse --format='commit %H%n%B%n--END--' a5cc8de5040107e121a199caf845358a395b98d0..HEAD` was also inspected. Each `Why:` paragraph explains lifecycle risk or regression-evidence need; none is a marker-only body.

### Check 5 — deterministic mapping grep

Changed test-path list came from:

```text
$ git diff --name-only a5cc8de5040107e121a199caf845358a395b98d0..HEAD -- 'tests/**'
tests/opsx-tui/SCENARIOS.md
tests/opsx-tui/fixtures/fake-openai-server.mjs
tests/opsx-tui/fixtures/fake-opsx.sh
tests/opsx-tui/scripts/run-scenario-s07-native-retry.sh
tests/opsx-tui/scripts/run-scenario-s08-retry-exhausted.sh
tests/opsx-tui/scripts/run-scenario-s09-overflow-recovery.sh
tests/opsx-tui/scripts/run-scenario-s10-overflow-persistent.sh
tests/opsx-tui/scripts/run-scenario-s11-clear-during-retry.sh
tests/opsx-tui/scripts/run-scenario-s12-rearm-during-retry.sh
```

Literal forward/reverse grep:

```text
$ grep -nH -F 'opsx-loop.interrupt-or-error-stops-the-loop' <all nine changed test-path files>
tests/opsx-tui/SCENARIOS.md:29-34
 tests/opsx-tui/fixtures/fake-openai-server.mjs:2
 tests/opsx-tui/fixtures/fake-opsx.sh:2
 tests/opsx-tui/scripts/run-scenario-s07-native-retry.sh:2
 tests/opsx-tui/scripts/run-scenario-s08-retry-exhausted.sh:2
 tests/opsx-tui/scripts/run-scenario-s09-overflow-recovery.sh:2
 tests/opsx-tui/scripts/run-scenario-s10-overflow-persistent.sh:2
 tests/opsx-tui/scripts/run-scenario-s11-clear-during-retry.sh:2
 tests/opsx-tui/scripts/run-scenario-s12-rearm-during-retry.sh:2
```

### Check 6 — constitution and cleanliness

```text
$ git grep -n -E '(AKIA[0-9A-Z]{16}|BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY|gh[pousr]_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9]{20,})' HEAD -- <all 12 changed files>
secret_pattern_matches=0
$ git diff --name-only a5cc8de5040107e121a199caf845358a395b98d0..HEAD -- 'dot_pi/agent/extensions/goal/**'
<no output; exit 0>
```

## Check 5 detail — AC↔test mapping (canonical ID format)

### Forward coverage (each AC has ≥1 test)

| AC ID | Test references | Status |
|---|---|---|
| `opsx-loop.interrupt-or-error-stops-the-loop` | `tests/opsx-tui/SCENARIOS.md:29-34`; `tests/opsx-tui/fixtures/fake-openai-server.mjs:2`; `tests/opsx-tui/fixtures/fake-opsx.sh:2`; `tests/opsx-tui/scripts/run-scenario-s07-native-retry.sh:2`; `run-scenario-s08-retry-exhausted.sh:2`; `run-scenario-s09-overflow-recovery.sh:2`; `run-scenario-s10-overflow-persistent.sh:2`; `run-scenario-s11-clear-during-retry.sh:2`; `run-scenario-s12-rearm-during-retry.sh:2` | covered |

### Reverse coverage (each changed test references ≥1 AC)

| Test file | AC references | Status |
|---|---|---|
| `tests/opsx-tui/SCENARIOS.md` | `opsx-loop.interrupt-or-error-stops-the-loop` (lines 29-34) | referenced |
| `tests/opsx-tui/fixtures/fake-openai-server.mjs` | `opsx-loop.interrupt-or-error-stops-the-loop` (line 2) | referenced |
| `tests/opsx-tui/fixtures/fake-opsx.sh` | `opsx-loop.interrupt-or-error-stops-the-loop` (line 2) | referenced |
| `tests/opsx-tui/scripts/run-scenario-s07-native-retry.sh` | `opsx-loop.interrupt-or-error-stops-the-loop` (line 2) | referenced |
| `tests/opsx-tui/scripts/run-scenario-s08-retry-exhausted.sh` | `opsx-loop.interrupt-or-error-stops-the-loop` (line 2) | referenced |
| `tests/opsx-tui/scripts/run-scenario-s09-overflow-recovery.sh` | `opsx-loop.interrupt-or-error-stops-the-loop` (line 2) | referenced |
| `tests/opsx-tui/scripts/run-scenario-s10-overflow-persistent.sh` | `opsx-loop.interrupt-or-error-stops-the-loop` (line 2) | referenced |
| `tests/opsx-tui/scripts/run-scenario-s11-clear-during-retry.sh` | `opsx-loop.interrupt-or-error-stops-the-loop` (line 2) | referenced |
| `tests/opsx-tui/scripts/run-scenario-s12-rearm-during-retry.sh` | `opsx-loop.interrupt-or-error-stops-the-loop` (line 2) | referenced |

## Check 6 detail — Constitution sampling

| Sampled file | Principles checked | Status | Notes |
|---|---|---|---|
| `dot_pi/agent/extensions/opsx-loop/index.ts` | I-X; applicable I, III | compliant | Deployed extension remains in chezmoi source. Deferred error belongs to exact loop object; top-level owner guards retries/replacement; abort remains immediate; overflow recovery remains one-shot. No secret or unrelated extension change. |
| `openspec/changes/preserve-opsx-loop-across-native-retries/plan.md` | I-X; applicable III, VIII | compliant | Repo-local, non-deployed workflow artifact; plan updated to match lifecycle-gap work and validation. |
| `openspec/changes/preserve-opsx-loop-across-native-retries/tasks.md` | I-X; applicable III, VIII | compliant | Repo-local task contracts match changed runtime, fixtures, docs, and six new scenarios; zero unchecked tasks. |
| `tests/opsx-tui/SCENARIOS.md` | I-X; applicable III | compliant | Documents deterministic AC signals for s07-s12; no credentials or deployment claims. |
| `tests/opsx-tui/fixtures/fake-openai-server.mjs` | I-X; applicable III | compliant | Status sequence and error text are opt-in; default remains HTTP 200/SSE success; values are synthetic. |
| `tests/opsx-tui/fixtures/fake-opsx.sh` | I-X; applicable III | compliant | Gate delay is opt-in and test-only; default behavior unchanged; no secret material. |
| `tests/opsx-tui/scripts/run-scenario-s07-native-retry.sh` | I-X; applicable III | compliant | Proves 500→200 native retry, exactly one post-success gate, and no extra provider turn. Executable mode is `100755`. |
| `tests/opsx-tui/scripts/run-scenario-s08-retry-exhausted.sh` | I-X; applicable III | compliant | Proves four native attempts, one visible final stop, no failed-attempt gate, and no extension retry. Executable mode is `100755`. |
| `tests/opsx-tui/scripts/run-scenario-s09-overflow-recovery.sh` | I-X; applicable III | compliant | Proves one settled overflow recovery and return to normal gate flow. Executable mode is `100755`. |
| `tests/opsx-tui/scripts/run-scenario-s10-overflow-persistent.sh` | I-X; applicable III | compliant | Proves persistent overflow stops after one recovery allowance and receives no third request. Executable mode is `100755`. |
| `tests/opsx-tui/scripts/run-scenario-s11-clear-during-retry.sh` | I-X; applicable III | compliant | Proves clear invalidates deferred ownership and stale completion cannot gate or stop cleared loop. Executable mode is `100755`. |
| `tests/opsx-tui/scripts/run-scenario-s12-rearm-during-retry.sh` | I-X; applicable III | compliant | Proves replacement ownership transfers on replacement user directive and old retry cannot gate replacement. Executable mode is `100755`. |

**Sampling coverage:** 12 audited of 12 changed = 100%. Because `10 < N <= 50`, no sampling was used.

## Summary

- Pass count: 6/6
- Decision: green
- **Archive gate:** READY

## Override (if archiving despite red)

Not used; verification is green.

## Findings

- P0: none.
- P1: none.
- P2: none.
- P3: none.

Verification Verdict: pass
