# Intent: add-opsx-design-fidelity-gate

**Status:** FROZEN — confirmed by owner 2026-07-05; do not edit without explicit human authorization
**Date:** 2026-07-05
**Owner:** cartwmic

## Problem

The 2026-07-05 oxide-clone `crypt-secret-structural-hardening` loop run (pi
session `019f2d9f-6550-76da-8980-8d8cfc5eaeb2`) exposed a semantic hole in the
pre-implementation quality stack: the frozen intent mandated a type-level
structural guarantee ("cleartext never enters the error value — safe by
construction"), the orchestrator-authored design.md D3 silently swapped that
mechanism for manual per-site redaction while its rationale *still claimed the
structural guarantee*, tasks faithfully encoded the wrong mechanism, and
workers implemented it with zero deviation. The analyze artifact's AC↔design
check (Check 3) validates only *nominal* coverage — an AC citing *some* design
section passes — so a design that satisfies an AC on paper but cannot deliver
its guarantee sails through. The defect surfaced only post-implementation, as
three rounds of P0 leak whack-a-mole, and root-caused to design only after an
owner escalation.

The general class is broader than the instance: a design with an *honest*
rationale ("we redact manually at known sites") and no explicit intent
rejection still fails the AC's guarantee — no contradiction-hunting catches
it. Only per-AC entailment ("does the chosen mechanism deliver this
guarantee?") closes the class.

## Goal

Add a **design-fidelity judge** to the opsx-superpowers workflow: a blind LLM
judgment, sealed into a deterministic artifact, read by the model-free gate,
that verifies each delta AC's guarantee is semantically *entailed* by the
design mechanism that claims to deliver it — before tasks are generated and
implementation begins.

### Judge scope — full per-AC entailment sweep (bounded)

- For EVERY delta AC of the change, the judge answers: does the design
  mechanism cited (or discoverable) for this AC entail the AC's guarantee as
  written? Verdict rows: `entailed | not-entailed | not-covered` with evidence.
- An AC with no substantive design coverage is `not-covered` (nominal citation
  to a section that does not address the guarantee does not count).
- **Bounded judge contract** (mirrors the reviewer baseline-bounded contract):
  a `not-entailed` / `not-covered` row is a BLOCKER only for clear
  non-entailment of the AC *as written*; where the AC's guarantee is ambiguous,
  the judge routes an advisory clarify-class finding instead of blocking —
  ambiguity resolution belongs to clarify, not fidelity.
- Intent-mandate violations (a design decision rejecting or weakening
  something the frozen intent mandates) and rationale↔mechanism contradictions
  are within scope and fall out of the per-AC sweep as evidence.

### Dispatch channel and artifact

- **Design-conditioned**: the fidelity judgment runs whenever the change has a
  `design.md`, at any Scale. No design.md ⇒ no fidelity requirement.
- **full_rigor**: fidelity is a REQUIRED section of the existing blind analyze
  dispatch (no additional dispatch), yet the verdict is STILL sealed to a
  separate `design-fidelity.md` (mirrors doneness riding the CR dispatch at
  plain M).
- **Plain M / design-bearing S**: one narrow post-design blind mini-dispatch
  produces the same sealed artifact.
- **Sealed artifact `design-fidelity.md`** (shipped template): per-AC verdict
  table, overall `Fidelity: delivered | violated`, judge provenance
  (adapter-stamped, blind), and **digest binding** — sha256 of intent.md,
  design.md, and every delta spec file recorded in the artifact; the gate
  recomputes and any mismatch fails the check (edit ⇒ re-judge). Re-judges are
  full sweeps, never deltas (no cross-round finding matching).
- The gate stays deterministic and model-free: it parses sealed fields and
  recomputes digests only.

### Gating semantics — blocking from day 1

- Enforcement point: fidelity must be `delivered` before tasks generation /
  implementation proceeds (analyze-blocker semantics), and the gate fails the
  change while a required fidelity verdict is absent, stale (digest mismatch),
  or `violated` — fail-closed.
- **Escalation valve**: two consecutive `violated` verdicts against an
  unchanged digest-relevant reasoning (design fixes landed between judgments
  but the same rows keep failing, or no fix can be landed) route to the
  decision-audit landing for a human ruling — a wrong judge cannot stall the
  loop unbounded. A human waiver is recorded in the artifact, never
  self-authored.
- Reviewer-dispatch integrity applies: the fidelity judge dispatch follows the
  tree-identity attestation and read-only window protocol shipped by
  `harden-opsx-reviewer-dispatch-integrity`.

## Non-goals

- No change to clarify, code-review, doneness, quiet-round convergence,
  disclosure, or verdict-freshness semantics beyond adding the new artifact.
- No delta-scoped re-judging, no cross-judgment finding matching.
- No model in the gate; no new opsx keyword grammar.
- The same-tree post-seal bookkeeping/staling interaction discovered on
  2026-07-05 is explicitly OUT OF SCOPE — queued as its own micro-change.
- Not a replacement for post-impl code review — fidelity judges the design's
  promise, code review judges the diff's delivery.

## Constraints

- Gate/CLI deterministic, model-free, BSD/macOS compatible (ADR-0007 lineage).
- Fail-closed everywhere: absent/unparseable/stale fidelity verdict on a
  design-bearing change is a failed check, never a pass.
- Existing archived changes are never retroactively invalidated; enforcement
  applies to changes entering the pipeline after deployment.
- Shipped surfaces move together: schema.yaml/template, `executable_opsx` gate
  checks, openspec-loop + openspec-propose/apply skill prose, analyze template
  (full_rigor ride-along section), and tests for every enforced behavior.
- Judge model resolution follows the existing role-model machinery
  (`opsx models`, review-role or a dedicated fidelity role — design decision).

## Acceptance sketch

- A design-bearing change without design-fidelity.md fails the gate; with a
  sealed `delivered` verdict and matching digests it passes that check.
- Editing design.md (or intent/delta specs) after sealing flips the check red
  until re-judged (digest mismatch).
- A `violated` verdict blocks tasks-generation progression per the loop skill,
  and the documented procedure routes the two-consecutive-fails case to the
  decision-audit landing.
- The oxide D3 shape — AC guaranteeing "safe by construction" mapped to a
  manual per-site mechanism — reproduces as `not-entailed` in a fixture-level
  test of the artifact/gate contract (deterministic parts) and as explicit
  dispatch-prompt instruction (judged parts).
- All existing suites stay green; new gate tests cover absent / stale-digest /
  violated / delivered artifact states at each dispatch channel.

## Grounding (verified at draft time)

- Nominal-only check: `templates/analyze.md` Check 3 "AC↔design coverage"
  (covered|missing|partial — no entailment judgment).
- Doneness-judge precedent for judged-verdict-sealed-artifact-read-by-gate:
  `executable_opsx` doneness block (~1046), `templates/doneness.md`,
  tier-conditioned dispatch channel (combined at plain M, independent at
  full_rigor) — the fidelity channel mirrors this pattern inverted (rides
  analyze at full_rigor, independent below).
- Attestation/read-only dispatch protocol: shipped at gate suite 141 /
  convergence 168 by `harden-opsx-reviewer-dispatch-integrity` (sealed
  2026-07-05, attested head 90f7383d16709754e7e92235c3e20d4c8e10d5e7).
- M-tier thinning (no blind analyze at plain M): opsx-adversarial-review spec
  "M-Tier Review Stack Thinning" — the plain-M mini-dispatch deliberately adds
  back a single narrow judged step, conditioned on design.md existence.
