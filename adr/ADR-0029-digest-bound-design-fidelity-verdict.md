# ADR-0029: Digest-bound sealed design-fidelity verdict, gate-checked deterministically

## Status

Accepted (2026-07-06, change `add-opsx-design-fidelity-gate`)

## Context

The oxide-clone `crypt-secret-structural-hardening` run shipped a design that
silently swapped the frozen intent's structural mechanism for manual per-site
handling; analyze passed on nominal citation. No artifact bound the judged
design bytes to the verdict, so edits after judgment were invisible.

## Decision Drivers

- "Edit ⇒ re-judge" must be mechanical, not procedural.
- Gate stays deterministic and model-free (ADR-0005 lineage).
- The judged inputs (intent, design, delta specs) live in the change dir on
  the integration checkout; worktree copies can be stale.

## Considered Options

- Fidelity section inside analyze.md — rejected: analyze is advisory at plain
  M; fidelity must block at every Scale.
- Judge re-run at gate time — rejected: model in the gate.
- Digest design.md only — rejected: intent and delta specs are the other two
  legs of the entailment.

## Decision Outcome

Sealed `design-fidelity.md` per design-bearing change: per-AC verdict table,
own-line `**Fidelity:**`, blind-dispatch provenance, integration-checkout
`Attested HEAD`, and one pinned-grammar sha256 digest line per bound file
(intent.md, design.md, every `specs/**/spec.md`). The gate recomputes every
digest from COMMITTED main-root content (`git -C <main-root> show HEAD:`),
enumerates the spec-file set and fails on any set difference (both
directions, waived seals included), locates digest lines by literal string
match (never path-into-regex), and fails closed on absent/stale/violated/
unparseable — field parsing plus sha256 only.

## Consequences

- Any post-seal edit to a judged input reddens the gate until a fresh full
  sweep re-seals; a post-seal spec-file addition/removal likewise.
- Uncommitted edits can never move the check in either direction
  (committed-read, ADR-0032/D8 companion).
- One tree of record kills the worktree-copy split-brain in both directions.
