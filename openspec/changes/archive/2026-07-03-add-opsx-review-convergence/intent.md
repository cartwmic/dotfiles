# Intent — add-opsx-review-convergence

Status: explore-frozen

## Intent

Fix the **review treadmill** in the opsx loop: today the gating review cycle
(blind code-review rounds, and review-verdict production generally) has no stop
condition, no convergence tracking, no split-verdict protocol, and an open-ended
verdict contract. Evidence (session 019f1ed4, oxide-clone, 2026-07-02): the
`crypt-log-redaction-ui-argv` change ran ~18-20 blind reviewer dispatches over
~4.5 hours — 6-8 gating rounds plus an ad-hoc 5-model "final convergence" blitz —
for a Scale-L change with pre-enumerated scope, because every fix commit moved
HEAD, invalidated the verdict, and re-opened an unbounded fresh review. The loop
could neither justify stopping nor resolve a PASS/FAIL reviewer split except by
improvising.

Make the gating review loop **converge or land**: bound what a reviewer may
block on, track the severity trajectory across rounds, stop on flat/rising
trajectory or a round budget, resolve persistent splits with one deliberate
disclosure round, and deliver non-convergence to the human as a tiered decision
audit — never a forced green, never an unbounded escalation.

## Design decisions (frozen)

- **Baseline-bounded verdict contract.** A gating reviewer may FAIL the review
  only for (a) a violation of the frozen baseline — intent.md, delta ACs,
  design decisions, constitution/domain — or (b) an objective
  correctness/security defect, even where the baseline is silent. Taste,
  style, alternative-design preference, and beyond-scope demands are advisory
  (P2/P3) and cannot gate. This ports the doneness judge's scope-anchored
  charter ("satisfied means the intent's outcomes are met and NOTHING MORE")
  to code-review and analyze verdict contracts.
- **Severity floor + calibration rubric.** `Verdict: pass` ⟺ no open P0/P1.
  P2/P3 findings are recorded and surfaced as warnings; they never force a fix
  round. The reviewer dispatch prompt embeds a P0-P3 rubric (P0
  baseline-violating/confirmed-critical … P3 nit) with a single declared
  severity lens, so trajectory counts are comparable across rounds. Rubric
  calibration is a hard dependency of trajectory tracking.
- **Finding routing + follow-ups.md.** Every finding is routed: in-scope
  blocking (P0/P1 within scope), in-scope advisory (P2/P3), or out-of-scope →
  appended to a `follow-ups.md` artifact in the change dir. At archive,
  follow-ups.md is surfaced as explore input for a successor change. This
  institutionalizes the "post-archive audit" at zero extra dispatch cost.
- **Orchestrator-side round ledger.** The orchestrator (never the reviewers)
  maintains a per-review-type round ledger: round number, per-severity finding
  counts, per-reviewer verdicts, HEAD reviewed. Recorded as structured
  front-matter/section in `code-review.md` (and mirrored for analyze rounds).
  Reviewers stay blind: the ledger, prior findings, and other reviewers'
  output NEVER enter a blind reviewer prompt.
- **Trajectory stop + round budget.** The loop stops dispatching further blind
  review rounds when (a) the round's P0+P1 count is 0 (converged), (b) P0+P1
  is flat or rising for 2 consecutive rounds (treadmill), or (c) a
  `review_max_rounds` budget (review.md front-matter, default 5, per-change
  override) is exhausted. (b) and (c) route to the disclosure/landing steps
  below — they are stop-and-land triggers, not failures to hide.
- **Full re-review every round.** Each gating round reviews the complete
  `Diff Base SHA..HEAD` diff with fresh blind reviewers — no delta-scoped
  rounds. Maximum per-round independence is deliberately retained; the stop
  conditions, not review-scope narrowing, contain the cost.
- **Split-verdict protocol: one late disclosure round.** WHEN reviewer
  verdicts split (some pass, some fail) on 2 consecutive rounds, OR a
  trajectory/budget stop fires while a split is present, the orchestrator runs
  ONE deliberately non-blind **disclosure round**: the same reviewers see each
  other's findings and must converge on a joint findings set + verdict. Max
  one disclosure round per change; its provenance is marked
  `review_mode: disclosure-consensus` so it is distinguishable from blind
  rounds. This is the only sanctioned blindness break.
- **Decision-audit landing.** IF open P0/P1 remain after stop conditions (and
  any disclosure round), the loop halts review cycling and synthesizes a
  tiered decision audit for the user — 🔴 need-your-call / 🟡 worth-a-glance /
  🟢 trust-me — covering open findings, autonomous fix decisions, and all
  scope expansions. The user rules; the loop resumes or the change is
  re-scoped. Non-convergence is delivered as information, never forced green,
  never escalated to additional ad-hoc reviewer models.
- **Prose scope + evidence-gated widening.** intent.md states the intended
  scope in prose (no rigid file/glob manifest). During the loop, WHEN a
  finding falls outside the intended scope, the orchestrator classifies it:
  required to meet the frozen intent (evidence cited) → **widen** the scope,
  log an entry in a `Scope Expansions` section of review.md (what widened +
  evidence), and fix in-change; not required → route to follow-ups.md. Intent
  *meaning* is never edited (frozen-intent invariant intact); scope of work
  may grow only toward satisfying it. Every widening surfaces in the decision
  audit / at gate-green.
- **Advisory surface audit for property-style intents.** WHEN an intent states
  a property over the codebase ("no X anywhere", "impossible via code"), the
  loop dispatches ONE advisory blind surface-enumeration audit before apply
  (explore/analyze phase), whose output feeds tasks and the intended-scope
  prose. Gating review remains post-apply and verification-only. Advisory
  reviews cannot loop (no fix-redispatch cycle) by construction.
- **Reviewer-model stability.** All blind rounds of one change use the
  resolved `review` role model set (`opsx models review` /
  `OPSX_REVIEW_MODELS`). Ad-hoc addition of extra reviewer models mid-change
  (reviewer shopping / escalating confirmation) is prohibited.

## Constraints

- **Gate stays deterministic.** Ledger/trajectory logic lives in the
  orchestrator skill + sealed artifact fields; `opsx gate` reads sealed
  fields/front-matter by exit-code logic and never runs a model.
- **Enforcement layer = skill prose + structured artifact fields** (templates,
  front-matter). No extension/gate mechanization of trajectory logic in this
  change; front-matter is designed so later mechanization needs no format
  change.
- **Do NOT modify the shared `review-plans` skill** (used by other projects);
  verdict-contract changes live in opsx reviewer dispatch prompts, opsx
  templates, and opsx specs.
- **Reuse existing machinery**: blind-subagent dispatch, provenance stamping,
  freshness fields, `review` role model resolution. No new model roles.
- **Do NOT modify the `goal` extension** (ADR-0006); harness-neutral core
  (ADR-0007).
- Constitution IX: this change edits existing skills (openspec-loop,
  openspec-apply-change references) → multi-model adversarial code review
  required.

## Invariants honored

- Frozen intent.md is never edited by the loop; scope widening changes work
  scope, not intent meaning, and is logged + human-surfaced.
- Blind review stays blind: ledger/prior-findings/round-tracker never enter a
  blind reviewer prompt; the single disclosure round is explicitly marked and
  bounded (max 1 per change).
- Deterministic gate decision logic over sealed fields preserved.
- Existing healthy convergence is not penalized: a declining-trajectory review
  (e.g. 4 rounds to 0/0) runs unchanged under these rules.

## Non-goals

- Oscillation/revert detection (commit-trailer blame guard) — deferred;
  observed treadmill churn was accretive, not oscillating; flat-count
  trajectory trip covers the residual.
- Extension/gate mechanization of the trajectory stop or ledger (prose +
  front-matter first; mechanize only if prose enforcement demonstrably fails).
- Delta-scoped or per-task gating reviews (rejected: breaks round
  comparability; multiplies treadmill surface).
- A rigid machine-readable surface manifest in intent.md (rejected in favor of
  prose scope + evidence-gated widening).
- Changing clarify's 3-pass gate, the doneness judge contract, or mechanical
  gate checks beyond reading the new sealed fields.
- Convergent-findings (quorum) gating and arbiter-on-split variants —
  considered and rejected in favor of the single disclosure round.

## Supersedes

- The implicit unanimous-pass split rule (all reviewers 0 P0/P1 on one HEAD,
  unbounded rounds) — replaced by trajectory stop + budget + disclosure round +
  decision-audit landing.
- The open-ended "find issues" reviewer charter for code-review/analyze —
  replaced by the baseline-bounded verdict contract.
