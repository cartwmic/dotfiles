# ADR-0032: Fidelity Round Ledger hosted in review.md; consecutive-violated valve with waiver streak-break

## Status

Accepted (2026-07-06, change `add-opsx-design-fidelity-gate`)

## Context

The escalation valve counts two consecutive `violated` fidelity verdicts, but
every re-judgment overwrites design-fidelity.md (full-sweep rule) and the
existing round-ledger hosts (code-review.md, analyze.md) don't exist at
fidelity time for the S/XS mini-dispatch channel — the count had nowhere to
live and would silently reset.

## Decision Drivers

- The count must survive session restarts and artifact re-seals.
- No per-row cross-round comparison (frozen-intent non-goal).
- review.md exists at every Scale and before worktree creation.

## Considered Options

- History structure inside design-fidelity.md — rejected: overwritten by
  every full-sweep re-seal (clarify C7).
- analyze.md ledger section — rejected: absent at design-bearing S/XS.

## Decision Outcome

The Orchestrator Round Ledger gains a third host: an append-only
`Fidelity Round Ledger` section of review.md with pinned machine-parseable
columns `| Round | Fidelity | Per-judge verdicts | Attested HEAD |`. Every
sealed fidelity round appends a row; a human waiver ruling appends a `waived`
row. The valve fires on two consecutive `violated` rows NOT separated by a
`waived` or `delivered` row — a resolved streak never re-fires against a
superseded round; a fresh post-waiver `violated` starts a new count of one.
Rows are orchestrator bookkeeping (Execution-Notes class); the gate never
reads them.

## Consequences

- Valve enforcement is session-durable and row-format-stable.
- This change's own authoring crossed the threshold (rounds 7–8) — live
  proof the substrate works.
