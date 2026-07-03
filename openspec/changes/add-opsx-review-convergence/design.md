<!-- authored: in-session -->
## Context

Gating reviews in the opsx loop are blind, freshness-bound (verdict valid only at the
reviewed HEAD), and — for skill edits — Constitution-IX multi-model. Nothing in the
current directives bounds the fix→re-review cycle: the openspec-loop skill re-dispatches
on every fail, the verdict contract is open-ended, splits between reviewers have no
protocol, and the only backstops (`loop_max_iterations`, the stall detector) do not see
review-round trajectory — change-dir churn resets the stall counter, so review-fix cycles
read as progress. Observed failure (session 019f1ed4, oxide-clone, 2026-07-02): 6-8
gating rounds plus an improvised 5-model "convergence blitz," ~4.5h, ~18-20 reviewer
dispatches, on a pre-enumerated Scale-L scope.

This change adds the convergence discipline as a new capability
(`opsx-review-convergence`) with thin additive bindings in `opsx-loop-orchestration`,
`opsx-post-impl-review`, and `opsx-workflow-schema`. It respects Constitution II
(canonical chezmoi sources), V (no new tools), IX (skill edits → multi-model adversarial
code review), ADR-0006/0007 (goal extension untouched; harness-neutral core, adapters
consume), and the frozen-intent invariant (loop never edits intent.md meaning).

## Goals / Non-Goals

**Goals:**
- Review rounds converge or land: bounded verdict contract, trajectory stop, round
  budget, one disclosure round, decision-audit landing.
- Blindness preserved: ledger/prior findings never enter a blind prompt; exactly one
  explicitly marked non-blind round.
- Deterministic gate untouched: all logic in skill prose + sealed artifact fields.
- Healthy convergence unpenalized (a declining 4-round review runs unchanged).

**Non-Goals:**
- Oscillation/revert detection (deferred; observed churn was accretive).
- Extension/gate mechanization of ledger/trajectory (front-matter designed so later
  mechanization needs no format change).
- Delta-scoped or per-task gating reviews; a rigid machine-readable surface manifest.
- Changing clarify's 3-pass gate or the doneness judge contract.

## Decisions

### D1: Discipline lives in one new capability; bindings stay thin

**Choice:** All convergence rules (contract, rubric/floor, routing, ledger, stops,
disclosure, landing, widening, stability, surface audit) are specified once in
`opsx-review-convergence`; the three modified capabilities get additive ADDED
requirements that bind to it.

**Alternatives considered:**
- **Spread rules across the existing capabilities.** Puts stop conditions in
  loop-orchestration, verdict semantics in post-impl-review, etc. Cons: the discipline's
  invariants (e.g. "a stop never forges green") span capabilities and would be stated
  twice or implied; drift risk on every future edit.
- **MODIFIED requirements rewriting existing blocks.** Cons: archive header-match
  fragility (observed in the 2026-07-02 session), larger review surface, no semantic
  gain — existing requirements are not contradicted.

**Rationale:** Single source of truth; additive deltas archive cleanly; binding
requirements keep each capability's spec self-explanatory.

**4-point test:** multiple ✓; lasting ✓; disagreement ✓; constrains future spec layout ✓
→ ADR candidate **Y**.

### D2: Trajectory stop on severity counts, not finding identity

**Choice:** The treadmill trip compares the P0+P1 *count* of the two most recent rounds
(flat or rising → stop). No cross-round finding matching.

**Alternatives considered:**
- **Gap-set ratchet on normalized findings** (doneness-style). Cons: blind free-text
  findings do not normalize across fresh reviewer contexts — same defect, new phrasing
  every round; the ratchet never trips. Rejected as the primary signal.
- **Semantic dedup via an extra model call.** Cons: adds a model to the stop decision;
  non-deterministic; cost.

**Rationale:** Counts are cheap, comparable (given the rubric + fixed reviewer set), and
ARC-proven. Oscillation and non-convergence both surface as flat counts.

**4-point test:** multiple ✓; lasting ✓; disagreement ✓; constrains later mechanization
(counts must stay sealed per round) ✓ → ADR candidate **Y**.

### D3: One late disclosure round as the split-resolution mechanism

**Choice:** Persistent split (2 consecutive split rounds, or a stop firing with a split
present) triggers exactly one non-blind consensus round (`review_mode:
disclosure-consensus`) among the same reviewers; max one per change; satisfies
Constitution IX when it consolidates ≥2 models.

**Alternatives considered:**
- **Unanimous-pass, unbounded** (status quo). Cons: round count scales with reviewer
  count × taste variance; the observed treadmill.
- **Convergent-findings (quorum) gating.** Findings gate only if ≥2 reviewers cite them.
  Cons: a real P1 only the stronger model spots never blocks; silently weakens the gate
  every round, not just at deadlock. Rejected by user decision.
- **Arbiter model on disputed findings.** Cons: introduces a third opinion — either an
  extra model (stability violation) or the same family rubber-stamping; still no forcing
  function for the original reviewers to reconcile.

**Rationale:** Blindness is the default and its one break is late, bounded, marked, and
consent-carrying (frozen in intent). Disagreement is the signal; disclosure forces the
signal to resolve itself before a human is interrupted.

**4-point test:** multiple ✓; lasting ✓; disagreement ✓; constrains future review modes ✓
→ ADR candidate **Y**.

### D4: Decision-audit landing instead of forced green or plain failure

**Choice:** Open P0/P1 after stops + disclosure → halt cycling, present a tiered
🔴/🟡/🟢 audit (open findings, autonomous decisions, scope expansions). A user waiver
records the finding as user-waived in follow-ups.md and removes it from the open set —
pass is then reached by explicit human authorization, never by the loop overriding a
blocker.

**Alternatives considered:**
- **Plain fail-report** (budget-exhausted style). Cons: dumps synthesis on the user at
  their lowest-context moment; no waiver semantics → deadlock on re-run.
- **Auto-waive advisory residue.** Already subsumed by the severity floor (P2/P3 never
  block); auto-waiving P0/P1 would forge green. Rejected.

**Rationale:** Non-convergence is information. The landing matches the user's standing
principle that automation stops before archive/deploy and the ARC Step-6 pattern already
in use.

**4-point test:** multiple ✓; lasting ✓; disagreement ✓; constrains loop UX ✓ → ADR
candidate **Y**.

### D5: Prose scope + evidence-gated widening (no manifest)

**Choice:** intent.md states scope in prose. Out-of-scope findings required to meet the
frozen intent widen scope with a logged `Scope Expansions` entry (what + evidence);
others route to follow-ups.md. intent meaning never edited.

**Alternatives considered:**
- **Machine-readable surface manifest (files/globs).** Cons: wrong manifest converts
  unknown-unknowns into designed blind spots; taxes explore; rigid for property intents.
  Rejected by user decision.
- **No scope concept — contract only.** Cons: "in scope" judged fresh each round from
  intent prose with no accountability trail; the change-2 widening-by-review would repeat
  silently.

**Rationale:** Keeps the frozen-intent invariant intact while giving the loop a
sanctioned, audited widening path — ARC's scope-discipline rule adapted for autonomy.

**4-point test:** multiple ✓; lasting ✓; disagreement ✓; constrains intent authoring ✓ →
ADR candidate **Y**.

### D6: Enforcement in skill prose + sealed artifact fields; mechanization deferred

**Choice:** The openspec-loop skill and templates carry the rules; code-review.md seals
the ledger; review.md front-matter carries `review_max_rounds` (orchestrator-read).
`opsx gate` decision logic unchanged.

**Alternatives considered:**
- **Extension/gate mechanization now.** Cons: the observed failure was missing rules, not
  rule bypass; the ledger format is new — mechanizing before the format stabilizes bakes
  in churn; gate neutrality (ADR-0007) argues for sealed-field reads only.

**Rationale:** Prose-first with mechanization-ready fields is the cheapest reversible
step; front-matter is specified so a later gate check needs no format migration.

**4-point test:** multiple ✓; lasting ~ (reversible by design); disagreement ✓;
constrains later mechanization ✓ → ADR candidate **Y** (borderline; promote if gate
mechanization follows).

## Risks / Trade-offs

| # | Risk | Likelihood | Severity | Mitigation |
|---|---|---|---|---|
| R1 | Reviewers misclassify real defects as advisory under the bounded contract | Medium | Medium | Correctness/security defects always gate even where baseline silent; rubric in every prompt; disclosure round re-examines classification disputes |
| R2 | Severity counts incomparable across rounds (rubric drift, model nondeterminism) | Medium | Medium | Fixed reviewer set (stability rule), rubric embedded verbatim each round, counts sealed per round in the ledger |
| R3 | Disclosure round anchors on the louder reviewer, laundering a wrong PASS | Low | Medium | Disclosure requires a joint findings set (not just a verdict); landing still fires if P0/P1 remain; max one disclosure |
| R4 | Scope-widening becomes a self-authorized scope-creep channel | Medium | Medium | Widening requires cited evidence tied to frozen intent outcomes; every entry surfaces at landing/gate-green; non-required findings must route to follow-ups.md |
| R5 | `review_max_rounds` too low kills healthy convergence on big changes | Low | Low | Default 5 > observed healthy 4-round case; per-change front-matter override |
| R6 | Prose-only enforcement rationalized past by a future orchestrator | Medium | High | Sealed ledger makes violations visible post-hoc; explicit red-flag lists in the skill; mechanization path pre-designed (D6) |

## Migration Plan

Deploy via chezmoi apply (Constitution II): skill + template edits land in canonical
sources, `run_onchange` hooks propagate. No repo-side migration: changes without ledger
fields or `review_max_rounds` gate exactly as today (absent → defaults). Rollback =
revert the docs/skill commits; no state format to unwind.

## Open Questions

- None blocking apply. Deferred by design: analyze-round ledger field format (behavioral
  commitment only, per clarify C2); gate mechanization of `review_max_rounds` (D6
  follow-up).
