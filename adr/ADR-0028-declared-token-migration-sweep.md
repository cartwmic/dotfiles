# ADR-0028: Declared-token migration sweep — deterministic whole-class validation before sampled review

## Status

Accepted (2026-07-04, change `quiet-round-review-convergence`)

## Context

Blind review rounds SAMPLE scattered prose surfaces; they do not sweep them.
Six of eight gating P0/P1s in the simplify-and-parallelize review were one
defect class — a stale instruction on one of ~12 shipped prose surfaces
contradicting the change's own matrix — found one instance per round. A
deterministic contradiction sweep run before its round 8 converged the
review immediately; it should have run before round 1. (This change's own
round 1 then re-proved the class: two stale sibling prose homes.)

## Decision

A change MAY declare retired tokens / forbidden patterns in `sweep.txt`
(one ERE per line; `#` comments, blank and whitespace-only lines ignored;
zero effective patterns = clean pass). `opsx sweep <change>` greps every
git-tracked file of the change's RESOLVED implementation checkout
(worktree when worktree-required) minus `openspec/**` and `adr/**` —
non-deployed history surfaces that legitimately record retired vocabulary.
Tri-state, loud: `SWEEP-HIT <pattern> <file>:<line>` → exit 1;
`SWEEP-ERROR <pattern>` (malformed ERE) → non-zero; clean → 0. `opsx gate`
runs the same sweep as a cheap check ONLY when sweep.txt exists — undeclared
changes carry zero new obligations. The openspec-loop skill runs the sweep
BEFORE dispatching review round 1.

## Consequences

- Rename/retire/migration-class changes kill the whole stale-prose class in
  one deterministic pass instead of one instance per blind round.
- Deterministic and model-free (gate never runs a model) — Constitution VII
  and ADR-0007 lineage hold.
- Live specs are NOT swept (they migrate at archive); the residual class is
  documented per-change in verify.md.
