# ADR-0030: Fidelity dispatch channels + purpose-keyed integration-checkout attestation

## Status

Accepted (2026-07-06, change `add-opsx-design-fidelity-gate`)

## Context

The fidelity judgment must land BEFORE tasks generation, when no
implementation worktree exists; the shipped tree-identity attestation
(reviewer-dispatch-integrity) demanded the dispatched worktree root, which
would strand every fidelity verdict INVALID — including post-worktree
re-judges after a digest-staling design edit.

## Decision Drivers

- Frozen intent pins fidelity pre-tasks; re-timing was not an option.
- full_rigor already runs a multi-model blind analyze dispatch — reuse it.
- Attestation must stay total: every dispatch attests the tree it was given.

## Considered Options

- Re-time fidelity post-worktree — rejected: contradicts intent; wastes apply.
- Separate fidelity dispatch at full_rigor — rejected: doubles dispatch cost
  for judges reading the same three inputs.
- Temporal ("pre-worktree") carve-out — rejected after analyze R6: strands
  post-worktree re-judges.

## Decision Outcome

full_rigor: the fidelity sweep rides the blind analyze dispatch as a REQUIRED
section of EVERY judge's prompt; plain-M / design-bearing S/XS: one narrow
post-design blind mini-dispatch. Judge models resolve via the existing
`review` role (no dedicated fidelity role). The attestation carve-out is
PURPOSE-KEYED: proposal-phase judgment classes (clarify, analyze, fidelity)
attest the integration checkout ALWAYS — before or after an implementation
worktree exists — while post-implementation classes (code review, doneness)
keep the unconditional worktree path check. Multi-judge consolidation is
deterministic fail-closed: canonical AC enumeration handed to every judge,
key-indexed worst-of per AC, absent AC ⇒ not-covered, sealed `violated` iff
any judge blocks (any-block-wins).

## Consequences

- Post-worktree fidelity re-judges are producible; the C2 permanent-INVALID
  trap is dead.
- A permissive split-verdict pick is structurally impossible.
- Fidelity freshness is carried by digests (ADR-0029), never a Reviewed Range.
