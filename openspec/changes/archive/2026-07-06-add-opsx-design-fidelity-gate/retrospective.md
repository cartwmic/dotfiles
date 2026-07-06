# Retrospective — add-opsx-design-fidelity-gate

**Change:** add-opsx-design-fidelity-gate (M + full_rigor)
**Range:** 40d6ff0..602a294 (pre-landing-rebase) · GATE-PASS 2026-07-06

## Wins

- **9-round blind adversarial analyze earned its cost**: R1–R8 surfaced 30+
  real defects pre-implementation — seven same-tree survivor requirements the
  original C1 sweep missed, the valve-persistence hole, the digest
  tree-of-record split-brain, the window exclusion blinding fidelity judges to
  their own subject matter, the review_mode parity hole. Every one would have
  shipped otherwise.
- **Dogfooding was the best test fixture**: the change's own review.md was the
  comment-safe key-detection fixture; its own sealed design-fidelity.md was
  the first artifact its own gate check validated; the deployed-gate locator
  split-brain hit during apply was live evidence for the D8 committed-read.
- **All 71 baseline test failures fully attributed** before migration — zero
  masked debt.

## Misses

- Clarify C1 claimed survivor-sweep completeness with 4 requirements; analyze
  rounds found 7 more. Grep-based survivor hunting should be a deterministic
  pre-clarify sweep, not a judged claim.
- Step-0 sequence (worktree before locator commit) tripped the deployed gate's
  worktree-side locator read — one avoidable repair commit.
- Commit-subject hygiene enforced only at verify time — 9 subjects needed a
  history reword that would have been unnecessary with a check-at-commit habit.

## Plan deviations

- Plan step 6's remnant sweep caught `capability-hooks.md` (outside task 3.2's
  contract) and the convergence suite's stale derivation assertions — both
  fixed in-phase rather than re-planned.
- verify check-5 forward mapping needed 20 surface assertions added post-hoc
  (prose-contract ACs); plan should have named the surface-assertion idiom in
  phase 5 from the start.

## Skill compliance

- delegation_mode subagent-required honored for all implementation tasks
  (5 delegate dispatches, contract-verified wrap-ups, main-agent writeback).
- Blind dispatch discipline held across 9 analyze + 1 code-review + 1 doneness
  rounds: findings files sole verdict source, dual-tree windows all clean,
  every attestation matched the dispatched tree/head.
- One logged deviation: R9 window counted despite an operator commit advancing
  integration HEAD (judged inputs untouched; attestations matched) — recorded
  in analyze.md incidents + follow-ups F3.

## Surprises

- Fidelity Round Ledger rows 7–8 crossed the valve threshold (two consecutive
  violated) during the change's own authoring — the valve the change defines
  would have fired on the change itself; R9 delivered resolved the streak.
- tasks.md checkboxes are worktree-read (D8 split consequence) — completion
  marks live on the implementation branch, integration copy is a mirror.

## Promote candidates

Scored via the 4-point test in design.md; D1–D7 promoted (D8 documented as a
D7 corollary, not independently contested).

### Candidate 1 — D1 digest-bound sealed fidelity verdict → ADR-0029
### Candidate 2 — D2 dispatch channels + purpose-keyed attestation → ADR-0030
### Candidate 3 — D3 deterministic human-waiver path → ADR-0031
### Candidate 4 — D4 Fidelity Round Ledger host + streak valve → ADR-0032
### Candidate 5 — D5 findings file sole verdict source → ADR-0033
### Candidate 6 — D6 dual-tree read-only dispatch window → ADR-0034
### Candidate 7 — D7 worktree-mandatory execution (supersedes ADR-0008) → ADR-0035
