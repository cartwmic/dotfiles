<!-- authored: in-session -->
# Capability: opsx-cli

## ADDED Requirements

### Requirement: Read-only worktree path emit

THE `opsx` CLI SHALL provide `opsx worktree path <change>` as a READ-ONLY subcommand
that prints the canonical convention worktree path for the change — the path `opsx
worktree ensure` would use absent a `--path` override — on stdout and exits 0, with NO
side effects (no branch or worktree creation); IF the path cannot be derived, THEN it
SHALL exit non-zero with an actionable message. Consumers needing the convention path
for fallback resolution (the opsx gate locator fallback and the loop extension's
`resolveWorktree`) SHALL obtain it from this single source rather than re-deriving it,
so path-derivation logic exists exactly once. Worktrees created with a `--path` override
are out of the fallback's reach BY DESIGN — the committed review.md locator (locator
publication requirement) is the primary mechanism that covers them.

#### Scenario: Path emitted without side effects
- **WHEN** `opsx worktree path <change>` runs for a change with no existing branch or worktree
- **THEN** it SHALL print the convention path and exit 0, and SHALL NOT create any branch, worktree, or file

#### Scenario: Gate and extension consume the single source
- **WHEN** the gate locator fallback or the extension's worktree resolution needs the convention path
- **THEN** each SHALL obtain it via the shared derivation (the gate internally, the extension via `opsx worktree path`), and NO consumer SHALL carry an independent copy of the derivation logic
