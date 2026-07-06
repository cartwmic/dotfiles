# ADR-0035: Worktree-mandatory execution — the mode is abolished at every Scale

## Status

Accepted (2026-07-06, change `add-opsx-design-fidelity-gate`)

**Supersedes:** ADR-0008

## Context

ADR-0008 made worktree-required the default at all Scales but retained
same-tree as an explicit override, and the shipped schema then derived
same-tree by tier at XS/S. Same-tree execution proved to be the root enabler
of the post-seal verdict-staling family (bookkeeping commits move the same
HEAD verdicts bind to) and blocks parallel development on one shared tree.

## Decision Drivers

- Owner mandate: worktree is the only way to work; not an option.
- Parallel development: N active changes = N isolated worktrees.
- Every same-tree special case in gate/skills/tests is deletable complexity.

## Considered Options

- Keep same-tree as explicit opt-out (ADR-0008's shape) — rejected: retains
  the dual-mode test matrix, the attestation carve-outs, and the staling trap.
- Derive worktree-required everywhere but keep the key — rejected: a dead key
  that can only confuse; fail-closed rejection is strictly clearer.

## Decision Outcome

Worktree execution is the only model at every Scale including XS. The
`worktree_mode` vocabulary is deleted; a declared key (any value, empty
included) fails the gate closed via front-matter key-presence parsing
(comments never trip it). Past Diff Base capture, a change with no valid
`opsx/<change>` worktree fails loudly everywhere (gate, validation stage,
migration sweep, `opsx sweep`) with the `opsx worktree ensure` re-home
remedy — never a silent integration-checkout evaluation. Landing requires
the branch (Land Base Currency); the same-tree archive exemption is deleted.
Orchestration fields move to committed integration-checkout reads;
implementation artifacts stay worktree-read (D8 split) — post-seal
bookkeeping structurally cannot stale worktree-bound verdicts.

## Consequences

- ADR-0008's Option-A same-tree-override clause is dead; this ADR supersedes
  it.
- XS typo-fix changes pay the worktree lifecycle (owner-accepted uniform
  ergonomics).
- Pre-deployment same-tree-shaped changes hit a fail-closed migration path
  with a named remedy.
