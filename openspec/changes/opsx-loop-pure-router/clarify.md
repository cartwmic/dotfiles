# Clarify — opsx-loop-pure-router

**Source:** blind three-pass clarify dispatch (ambiguity / inconsistency /
completeness) over the 2 delta spec files, cross-checked against the frozen
intent (`6a1a11c0…`), live capability specs, constitution, and domain invariants.
**Judge attestation:** `Attested HEAD: 068a7c03f15bf66d157a8cfcb7bb7f44e94a4173`,
`Attested Path: /Users/mcartwright/.local/share/chezmoi` (proposal-phase —
integration checkout). Raw findings:
`/tmp/opsx-clarify-opsx-loop-pure-router/clarify-findings.md`.
**Dispatch channel:** Cursor Task generalPurpose (loop disarmed in this
harness; `opsx_dispatch` armed-only — recorded as host-adapter path).
**Findings:** 17. **Resolution authority:** autonomous drive-to-green loop;
rulings recorded here; Option-B spec edits applied in the same commit.

## Pass 1 — Ambiguity (semantic-entropy lite)

| # | AC ref | Question | Option A (keep) | Option B (change) | Status | Resolution |
|---|---|---|---|---|---|---|
| A1 | opsx-loop.opsx-bookkeep-structured-meta-tool | Sibling meta allowlist open vs closed? | Keep open allowlist: design MAY add narrowly listed sibling INTEGRATION meta paths. | Close set to ONLY review.md + follow-ups.md. | answered | **A** — matches frozen intent ("narrowly listed sibling meta files design names"). |
| A2 | opsx-loop.opsx-bookkeep-structured-meta-tool | clear-hold enum present-and-refuse vs omitted? | clear-hold MAY appear but MUST always refuse. | Omit clear-hold from enum entirely. | answered | **A** — intent refuses agent-initiated hold clear; enum may include refused op for explicitness. Spec text clarified. |
| A3 | opsx-loop.armed-loop-forces-author-role-dispatch | Armed unset author: refuse vs legacy "no-session-fallback" wording? | Keep scenario meaning; body phrase = historical label. | Edit body to explicit refuse / no session fallback. | answered | **B** — body rewritten to match scenario (with I1). |
| A4 | opsx-loop.armed-loop-mutes-generic-subagent-tool | On clear: soft "not required" vs hard absence of dispatch/bookkeep? | Soft: exposure MAY follow snapshot. | Hard: restore snapshot such that opsx_dispatch/opsx_bookkeep absent unless pre-arm. | answered | **B** — armed-only surfaces; clear scenario updated. |
| A5 | opsx-skill-integration.skills-honor-configured-role-models | Scope of "judged" artifacts for author dispatch? | Narrow: propose/design/spec (+ review/impl roles). | Broaden: any change-dir write via dispatch or bookkeep. | answered | **A** — intent phase→role for judged work; bookkeep for meta; not every file. |
| A6 | opsx-skill-integration.skills-honor-configured-role-models | Multi-review: task XOR tasks[] equal, or prefer one? | Keep XOR; one opsx_dispatch call. | Require one preferred form when multi-review. | answered | **A** — retains opsx-dispatch-transparent XOR contract. |

## Pass 2 — Inconsistency (pairwise antecedent overlap)

| # | AC pair | Shared antecedent | Conflict on output | Option A (keep both) | Option B (resolve) | Status | Resolution |
|---|---|---|---|---|---|---|---|
| I1 | armed-loop-forces-author-role-dispatch body vs unset-author scenario | armed + author unset + opsx_dispatch(author) | Body "no-session-fallback" vs scenario refuse | Treat scenario as normative. | Edit body to match scenario. | answered | **B** — same edit as A3. |
| I2 | forces-author-dispatch + mutes-generic-subagent (bash retained) | armed + bash present | No-silent-author vs bash mutate residual | Keep both; residual = Non-goal. | Narrow one AC to forbid bash writes to judged paths. | answered | **A** — intent Non-goals accept shell residual; document only. |
| I3 | opsx-bookkeep + skills-honor-configured-role-models | armed + skill bookkeeping required | Skill needs ops for all bookkeep actions; enum underspecified | Design must cover; absence = design defect. | List mandatory enum ops in AC. | answered | **B** — enum floor added: append_ledger, set_hold, append_followup, append_execution_note. |

## Pass 3 — Completeness

| # | Combination | Question | Option A (intentional silence) | Option B (add new AC) | Status | Resolution |
|---|---|---|---|---|---|---|
| C1 | follow-ups bookkeep op × armed | No follow-ups scenario | Defer to design. | Add follow-ups append scenario. | answered | **B** — scenario added. |
| C2 | author dispatch × armed + author_in_session false | Only true/unset covered | Ignore-flag covers false. | Add explicit false scenario. | answered | **A** — requirement already ignores the flag. |
| C3 | set-hold empty reason × armed | Success needs non-empty; empty path silent | Ordinary validation. | Add IF empty/missing → refuse. | answered | **B** — scenario added. |
| C4 | arm D while armed for C | Re-arm/switch undefined | Out of pure-router scope. | Add switch/refuse AC. | answered | **A** — prior `/opsx-loop` re-arm behavior unchanged. |
| C5 | bookkeep × missing INTEGRATION target file | create vs refuse | Design/runtime detail. | Add create-vs-refuse AC. | answered | **A** — design owns bootstrap. |
| C6 | non-propose/design/spec writes × armed | tasks/clarify/analyze routing | Only propose/design/spec judged for author. | Enumerate all artifact write channels. | answered | **A** — design/tasks may refine; not required for intent outcomes. |
| C7 | bookkeep × design-allowlisted sibling | Sibling has no scenario | Silence until design names siblings. | Add allowlist accept/refuse AC. | answered | **A** — A1 keeps open allowlist; design names siblings later. |
| C8 | bookkeeping × disarmed | Armed mandates bookkeep; disarmed path? | Disarmed keeps today's edit/write. | Add disarmed bookkeep AC. | answered | **A** — pure-router constraints WHILE armed only. |

## Outstanding (status != answered)

(none)

## Spec edits applied from Option B

1. `opsx-loop` bookkeep: enum floor + clear_hold-always-refuse note; scenarios for empty set-hold reason + append follow-ups.
2. `opsx-loop` author override: body refuse wording (drop ambiguous "no-session-fallback").
3. `opsx-loop` mute: clear restores snapshot without `opsx_dispatch`/`opsx_bookkeep` unless pre-arm.

## Summary

- Pass 1 findings: 6; unanswered: 0; deferred: 0
- Pass 2 findings: 3; unanswered: 0; deferred: 0
- Pass 3 findings: 8; unanswered: 0; deferred: 0
- **Gate status:** READY for design
