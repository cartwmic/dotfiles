# Analyze — add-opsx-design-fidelity-gate

**Blind Verdict:** pass
**Method:** full_rigor adversarial analyze — 9 blind two-model rounds
(claude-bridge/claude-opus-4-8 + claude-bridge/claude-sonnet-5 per review.md
`review_models`), fresh full sweep every round (no cross-round disclosure, no
prior-findings leakage; blindness preserved per Orchestrator Round Ledger).
Every round dispatched with mandatory tree-identity attestation
(integration checkout — proposal-phase carve-out) and a read-only snapshot
window; verdicts consolidated exclusively from findings output files
(conversational replies never read as verdicts). The design-fidelity sweep
rode every dispatch as a required section per D2; fidelity outcomes sealed
separately (design-fidelity.md + review.md Fidelity Round Ledger).

**Final round (R9):** both judges `Analyze Verdict: pass`, `Fidelity:
delivered`, zero blockers, residuals minor/advisory only. Findings files:
`/tmp/aodfg-analyze-r{1..9}-{opus,sonnet}.md`.

## Round Ledger

| Round | HEAD reviewed | P0/BLOCKER | MAJOR | minor | Opus verdict | Sonnet verdict | Outcome |
|---|---|---|---|---|---|---|---|
| 1 | `116c611` | 1 | 3 | 2 | (pass, fidelity violated) | blockers, violated | 6 findings fixed → `6947eca` |
| 2 | `6947eca` | 2 | 1 | 4 | pass, delivered | blockers, delivered | fixes → `4367c47` |
| 3 | `4367c47` | 2 | 2 | 3 | blockers, delivered | blockers, violated | fixes → `00e50f7` |
| 4 | `00e50f7` | 2 | 1 | 3 | pass, delivered | blockers, delivered | fixes → `548e735` |
| 5 | `548e735` | 2 | 2 | 4 | pass, delivered | blockers, violated | fixes → `3ed7909` |
| 6 | `3ed7909` | 0 | 2 | 4 | pass, delivered | pass, delivered | MAJOR fixes → `185b613` |
| 7 | `185b613` | 1 | 1 | 3 | pass, delivered | blockers, violated | fixes → `90e207f`, `2ba9951` (R8 fixes) |
| 8 | `90e207f` | 0 | 1 | 5 | pass, delivered | pass, violated | fixes → `2ba9951` |
| 9 | `2ba9951` | 0 | 0 | 5 | pass, delivered | pass, delivered | QUIET — sealed |

(Counts are consolidated max-across-reviewers per severity; fidelity
column history lives in review.md's Fidelity Round Ledger.)

## What the rounds surfaced and fixed (all landed pre-seal)

- **Same-tree survivor completeness (R1–R3):** seven live requirements
  outside the original C1 four carried same-tree/`worktree_mode` semantics —
  Apply-time writeback, Orchestrator Round Ledger host, Migration Sweep Gate
  Check, Manifest Validation Execution, opsx-cli Migration Completeness Sweep
  Command, opsx-loop convention fallback, Required Artifact By Scale
  (lifecycle order). All MODIFIED in; final survivor greps (R7–R9, all live
  specs) clean.
- **Fidelity mechanics (R1–R5):** valve persistence host (Fidelity Round
  Ledger in review.md), digest tree-of-record (committed main-root content,
  `-C <main-root>` addressing, literal-string digest keys), spec-file
  set-equality, deterministic waiver path (+ landing entry + empty-waiver
  fail-closed + set-equality restated for waived seals), multi-judge
  fail-closed consolidation (key-indexed worst-of, any-block-wins, canonical
  AC enumeration), `review_mode` blind-dispatch vocabulary parity with
  doneness, guidance-order slot (analyze→tasks, unconditional cheap check).
- **Dispatch-window integrity (R2–R6):** dual-tree window concurrency
  carve-outs (path-scoped sibling commits, sibling uncommitted authoring,
  dispatched change's own bookkeeping files — committed or not), narrow
  bookkeeping exclusion (review.md + follow-ups.md only; judged inputs always
  void-eligible), symmetric surgical restore (sibling dirs never restored or
  deleted), purpose-keyed attestation carve-out (post-worktree fidelity
  re-judge never strands INVALID).
- **Non-staling invariant (R5, R8):** gate mode fields (including `scale` +
  `full_rigor`) read from COMMITTED integration-checkout content only;
  misplaced-bookkeeping staling backstop named fail-closed; waiver ledger row
  breaks the valve's consecutive-violated streak.
- **Traceability (R7):** ADR-0005 lineage corrected (intent.md's ADR-0007
  cite is a frozen-document miscite, noted not edited).

## Residual advisories (non-blocking, routed to follow-ups at apply)

1. R9-O-F1: pre-worktree fidelity judge reads working tree while digests bind
   committed content — pin "judged inputs committed before fidelity dispatch"
   at apply.
2. R9-O-F2: `worktree_mode` present-but-empty key needs a key-PRESENCE test,
   not `fm()` value non-emptiness — implementation detail for tasks.
3. R9-S-A1: ADR-0008 (worktree-required default) is completed/superseded by
   D7 — the D7 ADR promotion at archive must fill `Supersedes: ADR-0008` and
   annotate ADR-0008 `Superseded by:`.
4. R9-S-A2: pre-worktree shared-tree `.git/index.lock` contention between
   concurrent orchestrators — operational retry note, not a spec change.
5. R8-O-F3 (deferred, design-documented): doc-class requirements (Artifact
   graph definition, Per-Tier Review Stack) gain the fidelity template/
   dispatch mention at apply.
6. R5 sonnet advisory: sonnet R9 Part B row 5 — Manifest Validation cwd
   mechanism entailed by D7's general principle, not separately named
   (discoverable; advisory).

## Incidents

- R9 window: integration HEAD advanced `2ba9951 → bdce1c2` during the open
  window by an operator commit (`bdce1c2` "chore(pi): bump enabled codex
  model to gpt-5.5", touches only `dot_pi/agent/settings.json.tmpl`). Judged
  inputs identical across the advance; both judges attested the dispatched
  head `2ba9951` exactly. Round COUNTED (dogfood deviation: under the
  shipped-to-be void rule a non-change-dir commit voids — this incident is
  logged as evidence for a possible future carve-out for paths disjoint from
  the change's blast radius; not widened now, fail-closed retained).
- Stall-detector signals on long-running dispatch rounds (R1, R2, R6) were
  transient — every run completed and produced attested findings files.

## Attestation summary

Every counted round: `Attested Path: /Users/cartwmic/.local/share/chezmoi`
(integration checkout — proposal-phase carve-out), `Attested HEAD` equal to
the dispatched head listed in the Round Ledger. No INVALID verdicts; no
round voided; every window porcelain-clean.
