# ADR-0033: Findings file is the sole verdict source for every judged dispatch

## Status

Accepted (2026-07-06, change `add-opsx-design-fidelity-gate`)

## Context

Session 019f2d9f: a reviewer's conversational reply asserted "no
implementation changed" while its findings file cited real defects. Any
reply-trust path lets a persuasive freeform channel mask a structured one.

## Decision Drivers

- One structured channel with a contract beats two channels with one.
- INVALID-not-fail semantics already exist for attestation mismatches.

## Considered Options

- Reply as fallback when the file is absent — rejected: recreates the
  incident exactly where it bites (absent file = weakest moment).
- Reply/file cross-check — rejected: the freeform channel has no contract to
  check against.

## Decision Outcome

For every reviewer/judge dispatch (code review, doneness, design fidelity,
judged clarify/analyze), the orchestrator derives verdict, findings, and
attestation EXCLUSIVELY from the subagent's findings output file. The
conversational reply is never a verdict input. A findings file that is
absent or lacks the required verdict/attestation fields consolidates as
INVALID — excluded from gating, the round ledger, and the round budget;
incident recorded; re-dispatch.

## Consequences

- A lying or embellished reply is inert; only sealed file content counts.
- Dispatch prompts must always name an output file and its verdict grammar.
