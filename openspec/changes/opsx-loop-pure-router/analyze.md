# Analyze Findings — opsx-loop-pure-router

<!--
STRICTLY READ-ONLY at judge time. Consolidated by orchestrator from blind
findings files. Severity: blocker | major | minor.
-->

**Mode:** adversarial-review-cycle (full_rigor; 2 blind judges)
**Generated:** 2026-07-15
**Blind Verdict:** pass (max severity across reviewers: major; blockers=0)

**Dispatch channel:** Cursor Task generalPurpose ×2 (loop disarmed; host
adapter). Expected HEAD `3a12cfc331208aba81a72657cb060732adb8c446`.

## Round Ledger

| Round | Mode | Blockers (max) | Majors (max) | Minors (max) | Per-judge verdicts | Attested HEAD |
|---|---|---|---|---|---|---|
| R1 | blind adversarial | 0 | 1 | 5 | opus-path: pass (0/0/5); terra-path: pass (0/1/2) | 3a12cfc331208aba81a72657cb060732adb8c446 |

## Attestation summary

Both judges attested HEAD `3a12cfc331208aba81a72657cb060732adb8c446` and path
`/Users/mcartwright/.local/share/chezmoi` — match dispatch. No INVALID.

Raw judge bodies (Ask-mode blocked `/tmp` write): embedded in parent
transcript; stubs at `/tmp/opsx-analyze-opsx-loop-pure-router/r1-*-findings.md`.

## Check 1 — Constitution compliance (consolidated)

| Principle | Status | Rationale | Severity |
|---|---|---|---|
| I–III, VIII–IX | compliant | Extension under `dot_pi/…`; skills under canonical harness; no secrets; openspec not deployed; Scale M + full_rigor multimodel. | |
| IV–VII, X | inapplicable | No install/mise/launchd/Termux/memory surfaces. | |

## Check 2 — EARS pattern check

| # | File:line | AC | True positive? | Suggested rewrite | Status |
|---|---|---|---|---|---|
| E1 | specs/opsx-loop (author refuse wording) | WHEN dispatch + later "error" | no (FP) | — | noted |
| — | — | No true-positive WHEN-on-error ACs | — | — | — |

## Check 3 — AC↔design coverage

| AC ID | Design section reference | Status | Severity |
|---|---|---|---|
| opsx-loop.opsx-bookkeep-structured-meta-tool | D2, D6 | covered | |
| opsx-loop.armed-loop-forces-author-role-dispatch | D3 | covered | |
| opsx-loop.armed-loop-mutes-generic-subagent-tool | D1, D5 | covered | |
| opsx-skill-integration.skills-honor-configured-role-models | D4 | covered | |
| opsx-skill-integration.worktree-always-skill-discipline | D2, D4 | covered | |
| Artifact→role map beyond propose/design/spec (terra major) | Clarify C6 answered **A** (intentional silence) | resolved | major→closed |

**Orchestrator resolution (terra major):** Not a frozen-baseline gap. Clarify C6
Option A kept author MUST-dispatch narrow to propose/design/spec; other
artifacts follow prior conventions / apply-phase impl. No design edit required
before tasks. Track as residual advisory only.

## Check 4 — design↔ADR promotion candidates

| Decision | 4-point score | ADR-candidate? | Rationale |
|---|---|---|---|
| D1 | 4 | yes | Armed tool-surface mute/restore |
| D2 | 4 | yes | opsx_bookkeep trust boundary |
| D3 | 3 | no* | Local plan helper (*terra said yes; design self-scored N — archive skill decides) |
| D4 | 3 | no* | Skill routing (*terra yes; prefer design N) |
| D5 | 2 | no | Host literal pin |
| D6 | 3 | no* | Module shape (*terra yes; prefer design N) |

Archive offer (consensus): **D1, D2**. D3/D4/D6 optional at archive skill discretion.

## Check 5 — Duplicate detection

| # | Locations | Restated constraint | Action |
|---|---|---|---|
| Dup1–3 | loop ACs ↔ skill ACs (bookkeep / author / mute) | Same outcomes, different layers | differentiate — keep both |

## Check 6 — Implementation language in specs

| # | AC ID | Tech mentioned | Rewrite suggestion |
|---|---|---|---|
| Imp1 | mute AC | `edit`/`write`/`subagent` / "pi exposes" | Acceptable host tool-surface contract — no rewrite |

## Check 7 — Unresolved clarify findings

| # | clarify.md ref | Status | Risk |
|---|---|---|---|
| — | — | none unanswered/deferred | — |

## Outstanding risks

| # | Source | Risk | Severity |
|---|---|---|---|
| OR1 | Intent / R1 | Bash mutate residual while armed | minor (accepted Non-goal) |
| OR2 | clarify C5 | Missing INTEGRATION file create-vs-refuse | minor (design-time) |
| OR3 | R2 / D5 | Host edit/write name drift | minor |
| OR4 | R4 | Unset author → armed propose stuck | minor |
| OR5 | terra Check3 | Narrow author artifact scope under mute | minor (clarify C6 A) |
| OR6 | empty set-hold | Design refuse matrix covers; call out in tasks tests | minor |

## Summary

- Blockers: 0 → tasks MAY proceed
- Major findings: 1 recorded → closed via clarify C6 Option A (no artifact edit)
- Minor findings: ≤5
- **Gate status:** READY for tasks

## Incidents

- Ask-mode sandbox blocked judge writes to `/tmp/.../r1-*-findings.md`; parent
  persisted stubs + sealed this consolidation from judge reply bodies (attested
  HEAD/path verified in replies).
