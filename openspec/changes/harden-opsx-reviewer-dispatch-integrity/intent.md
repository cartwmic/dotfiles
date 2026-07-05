# Intent: harden-opsx-reviewer-dispatch-integrity

**Status:** FROZEN — confirmed by owner 2026-07-05; do not edit without explicit human authorization
**Date:** 2026-07-05
**Owner:** cartwmic

## Problem

The 2026-07-05 opsx-loop run for `crypt-secret-structural-hardening`
(oxide-clone repo, pi session `019f2d9f-6550-76da-8980-8d8cfc5eaeb2`) surfaced
two reviewer-dispatch integrity failures that nothing in the workflow detects
mechanically:

1. **Wrong-tree review.** A blind reviewer (gpt-5.5 slot) was dispatched
   without `cwd` pinned to the worktree and reviewed the integration checkout
   (`main`, docs-only) instead of the implementation worktree — in two separate
   rounds. Its verdicts were dispatch artifacts, not reviews. The orchestrator
   only noticed because the findings text was incoherent with the diff; a
   plausible-sounding wrong-tree "pass" would have counted toward multi-model
   gating.

2. **Read-only contract violation.** In round 3 the same reviewer slot *edited
   five worktree files mid-review* — unvalidated, unreviewed code changes — and
   self-declared "pass". The read-only expectation exists only as prose in the
   dispatch prompt. The orchestrator discovered the edits by manual `git
   status` inspection and discarded them by hand; nothing mechanical voids a
   verdict produced by a reviewer that mutated the tree it was judging.

Both failures corrupt the core guarantee of the adversarial-review stack: a
verdict is only meaningful if it was computed *read-only* against *the exact
tree named in the reviewed range*.

## Goal

Make reviewer-dispatch integrity mechanically checkable, deterministically and
model-free, at every Scale where blind reviewer/judge subagents are dispatched:

**G2 — tree-identity attestation.**
- Every blind reviewer/judge dispatch prompt SHALL require the subagent to
  begin by attesting the tree it is actually reviewing: run
  `git rev-parse HEAD` (and record the working-directory path) in its own
  execution context, and record both in its findings output as machine-readable
  fields.
- The orchestrator SHALL refuse to count (treat as invalid, not as fail) any
  reviewer verdict whose attested HEAD does not equal the dispatched range head
  or whose attested path does not resolve to the dispatched tree; an invalid
  verdict never satisfies multi-model gating and never enters the round ledger
  as a reviewer verdict.
- The sealed verdict artifacts (code-review.md; doneness.md where an
  independent judge is dispatched) SHALL carry the per-reviewer attested
  HEAD(s), so the gate's existing freshness machinery can bind attestation to
  the recorded Reviewed Range deterministically.

**G3 — read-only enforcement.**
- The orchestrator SHALL capture a deterministic tree-state snapshot of the
  reviewed tree immediately before each reviewer/judge dispatch and compare it
  immediately after the subagent returns (worktree dirty-state; committed HEAD).
- Any delta attributable to the review dispatch SHALL void that reviewer's
  verdict (invalid, not fail), and the orchestrator SHALL restore the reviewed
  tree to its pre-dispatch state before proceeding and record the incident in
  the round ledger / Execution Notes.
- Enforcement SHALL be deterministic and model-free (plain git commands), and
  SHALL work in both worktree and same-tree modes.

## Non-goals

- **G1 (design-fidelity semantic gate)** — verifying that design mechanisms
  deliver AC guarantees is a separate successor change (explore pending).
- No change to blindness rules, quiet-round convergence semantics, disclosure
  rounds, severity rubric, or the verdict contract.
- No new review roles, models, or artifacts beyond fields/prose/checks needed
  for attestation and read-only enforcement.
- No sandboxing/containment of reviewer subagents (detection + voiding, not
  prevention).

## Constraints

- Gate and CLI stay deterministic and model-free (ADR-0007 lineage); BSD/macOS
  tool compatibility (no GNU-only flags).
- opsx keyword grammar unchanged.
- Fail-closed where a gate check is added: a required attestation field that is
  absent or unparseable is a failed check, not a pass.
- An *invalid* (voided) verdict is distinct from a *fail* verdict: it neither
  gates nor counts toward `review_max_rounds` convergence trajectory; the round
  is re-dispatched or the reviewer set is repaired.
- Existing artifacts/templates gain fields additively; existing valid archived
  changes must not be retroactively invalidated (attestation enforced for new
  verdicts only).
- Updated surfaces ship together: `executable_opsx` (if gate field checks are
  added), schema templates (code-review.md, doneness.md), openspec-loop skill,
  openspec-apply-change reference, and tests for every behavior added.

## Acceptance sketch

- A verdict artifact missing per-reviewer attestation fields fails the gate's
  code-review check when code review is gating-required (fail-closed).
- An orchestrator following the skill cannot count a wrong-tree verdict: the
  documented dispatch/consolidation procedure rejects a mismatched attested
  HEAD before sealing.
- The documented procedure detects a reviewer-mutated tree via snapshot
  compare, voids the verdict, restores state, and records the incident.
- All existing test suites stay green; new tests cover: attestation present +
  matching (green), attestation absent (red), attestation mismatched
  (procedure rejects), snapshot-delta voiding path.

## Grounding (verified in repo at draft time)

- `code-review.md` template already carries `Reviewed Range` +
  `reviewer-provenance` + `Diff Base SHA` (gate-read verbatim); no per-reviewer
  tree attestation exists.
- `executable_opsx` `freshness_check()` (~line 950) validates recorded range
  against current Diff Base / implementation HEAD but has no reviewer-side
  attestation input.
- Live spec home for the reviewer dispatch contract:
  `openspec/specs/opsx-adversarial-review/spec.md` (rubric-in-dispatch,
  blindness, ledger requirements); gate checks live in
  `openspec/specs/opsx-gate-enforcement/spec.md`; skill prose in
  `openspec-loop` SKILL + `openspec-apply-change` opsx-superpowers-mode
  reference.
