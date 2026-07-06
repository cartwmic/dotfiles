# ADR-0031: Deterministic human-waiver path for a violated fidelity verdict

## Status

Accepted (2026-07-06, change `add-opsx-design-fidelity-gate`)

## Context

The escalation valve routes irresolvable `violated` verdicts to a human
ruling, but the gate's only pass condition was `Fidelity: delivered` — a
legitimately waived change could never go green, breaking gate-as-arbiter.

## Decision Drivers

- The gate is model-free; the waiver check must be a field test.
- A self-authored `delivered` is the forgery class this change kills.
- Doneness already ships the precedent: `doneness_mode: waived` + rationale.

## Considered Options

- Land waived changes outside the gate (loop_hold + manual merge) — rejected:
  permanent red on a waived change breaks every downstream automation.
- Waiver rewrites `Fidelity: delivered` — rejected: self-authorable forgery.

## Decision Outcome

`Fidelity: violated` plus a non-empty own-line `**Human Waiver:**` naming the
ruling and its decision-audit landing entry = satisfied check. Written only
by a human ruling at the landing, never self-authored. Digest bindings,
spec-file set-equality, and fail-closed parsing apply to waived seals
identically — a waiver does not survive post-waiver edits. Empty or
whitespace-only waiver never waives. Authorship enforcement lives in the
landing record + retrospective audit (doneness-waiver parity), out of the
no-sandboxing scope.

## Consequences

- Waived changes have exactly one enumerable deterministic green path.
- The gate cannot verify a human wrote the field (accepted risk R7);
  history audit is the enforcement surface.
