# Retrospective: simplify-and-parallelize-opsx-workflow

**Date:** 2026-07-03 · **Scale:** XL (last change gated under the 5-tier schema)

## What went well

- Audit-first scoping paid off: an independent simplicity audit cut the flock,
  nonce, and branch-first re-architecture before any code existed, and the
  replacement (`opsx status` visibility + deterministic land checks) survived
  eight adversarial rounds without a design reversal.
- The gate caught its own migration hazards: the change's tests pin the NEW
  3-tier binary from the worktree while the change itself stayed gated by the
  deployed 5-tier gate — the self-referential wrinkle was contained by design
  (D3) and never leaked.
- Every one of the eight in-diff P0/P1 review findings was real, reproduced,
  fixed same-round, and pinned — including two only reproducible against the
  real openspec CLI (XS/S ungateable; invalid `git commit -- path -m` order).

## What hurt

- **Review-round churn:** rounds 5–7 each needed a human budget ruling while
  findings were monotonically shrinking and every fix landed same-turn. The
  flat-or-rising severity trajectory rule cannot distinguish recirculation
  (the crypt-log thrash it was written for) from fresh discovery at a constant
  rate across a large prose surface. Three rulings for one decision.
- **Scattered prose surfaces:** six of eight P0/P1s were the same defect class
  — a stale instruction on one of ~12 shipped surfaces contradicting the new
  tier matrix. Blind rounds sample; they don't sweep. The deterministic
  contradiction sweep run before round 8 converged the review immediately and
  should have run before round 1.
- **Verdict-format archaeology:** sealing required reverse-engineering the
  deployed gate's bold-field formats (`**Verdict:** pass`, `**Doneness:**`,
  `reviewer-provenance:`) instead of filling the shipped templates.
- Pinned second reviewer (gpt-5.5) hit a usage limit mid-round-8; the
  reviewer-model-stability spec correctly forced a human reconfiguration
  (→ sonnet-5), but the loop stalled until the ruling arrived.

## Actions (queued follow-up change, user-approved)

1. Quiet-round convergence semantics as the default budget mode: 0 new P0/P1
   from all reviewers ⇒ seal; findings + fix-commits-landed ⇒ continue
   autonomously; findings + no progress ⇒ land (thrash guard); hard cap ⇒
   land. Deterministic (per-round counts + HEAD-moved signal).
2. Migration-completeness sweep validator: retire-class changes declare
   retired tokens/forbidden patterns; grep validator over all shipped
   surfaces runs before review round 1.
3. openspec-loop skill points the orchestrator at the verdict templates
   instead of free-writing verdict artifacts.

## Follow-up seeds preserved (code-review.md warnings)

Template prose-table Code Review Mode row stale (P2); duplicate `gate` usage
line (P3); stray empty `.tmp` test file committed at 329a018 (P3 — delete in
the follow-up); schema.yaml artifact `requires` chain not thinned for plain M
(P3); audit remaining mode keys for fail-open-by-omission.
