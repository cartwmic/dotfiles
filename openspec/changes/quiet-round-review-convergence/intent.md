# Intent: quiet-round-review-convergence

<!-- FROZEN at loop arm. Distilled from the 2026-07-03 post-archive
     conversation (user-approved scope) following the 8-round review of
     simplify-and-parallelize-opsx-workflow. First change authored under the
     3-tier schema (M + full_rigor). -->

## Intent

Replace the review budget's per-stop human rulings with **ARC-style
autonomous convergence semantics, expressed deterministically**: gating
review rounds continue on their own while they are converging, stop
themselves at a quiet round, and land for a human ruling only on genuine
thrash or the hard cap. Additionally, close the two mechanical gaps the
8-round experience exposed: blind rounds sample scattered prose surfaces
instead of sweeping them, and verdict sealing requires reverse-engineering
the gate's field formats instead of filling the shipped templates.

## Grounding (observed, 2026-07-03)

- `simplify-and-parallelize-opsx-workflow` took 8 rounds and three human
  budget rulings while findings were monotonically shrinking and every fix
  landed same-round — the flat-or-rising severity-trajectory rule cannot
  distinguish recirculation (the crypt-log-redaction thrash it was written
  for, ADR-0017) from fresh discovery at a constant rate.
- Six of eight in-diff P0/P1s were one defect class: a stale instruction on
  one of ~12 shipped prose surfaces contradicting the change's own matrix. A
  deterministic contradiction sweep run before round 8 converged the review
  immediately; it should have run before round 1.
- Sealing verify/code-review/doneness required discovering bold-field formats
  (`**Verdict:** pass`, `**Doneness:** satisfied`, `reviewer-provenance:`)
  by gate archaeology although filled-in templates ship with the schema.

## In scope

- **Q1 — quiet-round budget semantics (default):** after each gating review
  round, evaluate in order:
  1. **Quiet round** — latest round yields 0 new P0/P1 across ALL reviewers →
     seal `Verdict: pass`, stop rounds (converged).
  2. **Converging** — findings present AND fix commits have landed since the
     previous round (worktree HEAD moved) → fix and dispatch the next round
     autonomously, NO human ruling.
  3. **Thrash guard** — findings present and NO progress since the previous
     round → decision-audit landing (current behavior).
  4. **Hard cap** — completed rounds ≥ `review_max_rounds` → decision-audit
     landing regardless.
  All conditions are per-round severity counts + the existing HEAD-moved
  progress signal — NO cross-round finding-identity matching (deterministic,
  model-free, ADR-0007 lineage). The current land-on-every-budget-stop
  behavior remains available as an explicit opt-in mode.
- **Q2 — migration-completeness sweep:** a change may declare retired
  tokens / forbidden patterns (machine-readable list in the change dir); a
  deterministic validator greps ALL shipped surfaces for them and fails on
  hits. The openspec-loop skill runs the sweep BEFORE dispatching review
  round 1 for rename/retire/migration-class changes.
- **Q3 — verdict artifacts from templates:** the openspec-loop skill directs
  the orchestrator to fill the schema's shipped verify/code-review/doneness
  templates (which already carry the gate-parsed field formats) rather than
  free-writing verdict artifacts.
- **Q4 — riders (follow-up seeds from the archived change's code-review
  warnings):** fix the review.md template prose-table Code Review Mode row
  (stale literal `advisory`); remove the duplicate `gate` line in
  `opsx_usage()`; delete the stray empty
  `tests/opsx-review-convergence/test_review_convergence_surfaces.sh.tmp`;
  audit remaining mode keys for fail-open-by-omission and derive fail-closed
  defaults where the docs promise them.

## Constraints

- Extension + gate + convergence logic stay deterministic and model-free; no
  cross-round finding matching of any kind.
- The 2-model blind adversarial code review is untouched in rigor: reviewer
  set stability (user-only reconfiguration), verdict contract, severity
  rubric, round ledger, single disclosure round, freshness/provenance
  binding all carry over unchanged.
- A stop with open P0/P1 still NEVER seals pass — Q1 only changes when the
  loop may *continue*, never when it may *seal*.
- Thrash guard must catch the crypt-log-redaction class: repeated rounds
  with findings but no landed fixes land for a human ruling.
- ADR-scarred guards (loop_hold, latch, distill confirm, locator, budgets,
  stall detection) untouched.
- Capability homes: opsx-adversarial-review (Q1), opsx-cli +
  opsx-gate-enforcement as needed (Q2 validator, Q4 gate fixes),
  opsx-skill-integration / skill prose (Q2 trigger, Q3), opsx-workflow-schema
  (Q1 mode key, Q2 declaration format).
- Constitution IX applies (existing-skill edits → gating multi-model review).

## Non-goals

- Semantic/LLM-based finding deduplication or cross-round matching.
- Changing reviewer counts, models, or the disclosure-round limit.
- Reworking the doneness judge or the M-tier dispatch shapes (ADR-0026
  stands).
- Retroactive changes to archived review records.
- Auto-archive/auto-deploy (human retains archive + deploy).

## Scale

**M + `full_rigor: true`** (cross-capability: adversarial-review, cli,
gate-enforcement, workflow-schema, skill surfaces; changes the review
discipline itself → ADR-worthy; former-L class under ADR-0025's mapping).
