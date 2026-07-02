# ADR-0012: Semantic doneness judged by a sealed, gate-read LLM verdict

**Status:** Accepted
**Date:** 2026-07-02
**Source change:** `openspec/changes/archive/2026-07-02-add-opsx-doneness-judge/`
**Supersedes:** —
**Superseded by:** —

## Context

The `opsx` gate proves only *mechanical* doneness — build/test/lint exit 0, required
artifacts present, review verdicts present — and cannot tell whether a diff actually
accomplished what the frozen `intent.md` asked. A change can be mechanically green while
missing the intent or drifting scope, and under an unbounded loop budget the orchestrator
stops at that false green. Prior design (ADR-0005/0006 era) explicitly framed opsx doneness
as "deterministic; no LLM judgment." This ADR reverses that stance for the intent-satisfaction
axis, while preserving the gate's deterministic decision logic. Constrained by Constitution II
(deterministic gate authority), IX (blind adversarial review for skill edits), V (no new
dev-tool install), and ADR-0006/0007 (goal extension untouched; harness-neutral config/enforcement).

## Decision Drivers

- Enforce intent-satisfaction without sacrificing the gate's reproducible, exit-code decision logic.
- Reuse the existing sealed-verdict + provenance + freshness machinery (`code-review.md`), not a parallel system.
- Bound the loop under an unbounded budget (no runaway spend on a stubborn judge false-negative).
- Harness-neutral: enforcement lives in the `opsx` CLI + artifacts, not the pi extension.

## Considered Options

### Option A: Sealed verdict, gate reads it (CHOSEN)
A blind subagent (on the resolved `review` role) judges intent vs the `Diff Base..HEAD` diff and
seals a `Doneness: satisfied | not` verdict + gaps + provenance + fresh reviewed range into a
dedicated `doneness.md`. The gate READS the field (no model in the gate), enforced at Scale ≥ M
when `doneness_mode: required` (waiver needs a real rationale), emitted only as the sole remaining
failure. **Pros:** deterministic gate preserved; reuses code-review pattern; judged once per HEAD.
**Cons:** needs a doneness-aware backstop under ∞ budget.

### Option B: Live per-turn LLM judge in the loop (goal-style)
A model call each `agent_end` decides stop. **Cons:** non-deterministic stop condition, per-turn
cost/latency, flip-flop, self-judgment bias. Rejected.

### Option C: Fold doneness into the code-review Verdict
No new artifact. **Cons:** collapses two orthogonal axes (code correctness vs intent satisfaction)
into one bit; the gate can't distinguish "code bad" from "intent unmet". Rejected.

## Decision

Adopt Option A across four coupled decisions:

- **D1 — Sealed verdict, gate reads it.** The gate performs no model call; it parses `doneness.md`.
- **D2 — Dedicated artifact + dedicated blind judge.** `doneness.md` + an independent judge on the
  `review` role (no new model role), baseline = frozen intent + diff + delta ACs, scope-anchored
  (no gold-plating).
- **D3 — Doneness gates loop-stop.** Required at Scale ≥ M (`doneness_mode: waived` + non-empty
  rationale escapes); the loop is not green until the verdict is `satisfied`, fresh, and provenanced
  (`review_mode` present and not `degraded-single-model`).
- **D4 — Doneness-aware stall is the sole ∞-budget backstop.** When the sole failing check is
  `doneness`, "progress" is the judge's normalized gap set strictly shrinking against a running
  minimum; the empty-set sentinel never counts as progress and never overwrites the minimum, so an
  agent churning files without closing judged gaps trips the stall instead of looping forever.

## Consequences

**Positive:** intent-satisfaction is enforced deterministically; the gate stays reproducible;
freshness re-judges on every new commit; the ∞-budget infinite-loop hole is closed by the gap-set
ratchet.

**Negative / trade-offs:** a judge dispatch per convergence attempt (mitigated: only after mechanical
green, freshness avoids re-judging an unchanged HEAD); the `doneness_waiver_rationale` reader is a
lightweight text reader, not a full YAML parser — accepted as a self-attested waiver (same tripwire
posture as the in-session authoring marker; full fidelity would need a `yq` dependency in the gate,
Constitution V).

**Scope:** applies to loop-driven Scale ≥ M changes. Existing archived changes untouched. The
introducing change (`add-opsx-doneness-judge`) waived its own doneness (bootstrap circularity — its
gate check is the machinery under construction).
