# opsx-loop (delta)

## MODIFIED Requirements

### Requirement: Worktree resolution convention fallback

THE opsx-loop extension's worktree resolution SHALL fall back to the canonical
convention path used by `opsx worktree` WHEN the `Worktree Path` locator in review.md is
absent, empty, or fails validation, obtaining that path from the opsx CLI's read-only
worktree-path interface (single-sourced — never re-derived independently in the
extension) and using the fallback iff the probed path is a valid git worktree for the
change's branch (`opsx/<change>`); WHEN both the locator and the convention path fail,
resolution SHALL yield no worktree and the extension SHALL still invoke the gate,
which fails the verdict evaluation loudly for a change past Diff Base capture
(opsx-gate-enforcement Worktree Mandatory Gate Enforcement) — never a guess, and
never a silent no-worktree evaluation.

#### Scenario: Empty locator resolves via convention path
- **WHILE** review.md in the integration checkout carries no usable `Worktree Path`
- **IF** the canonical `opsx worktree` path for the change exists and is a valid git worktree on branch `opsx/<change>`
- **THEN** the extension SHALL resolve that path and pass it as the gate's `--worktree`

#### Scenario: No locator and no convention worktree fails loudly at the gate
- **WHILE** the locator is empty AND the convention path is absent or invalid
- **THEN** resolution SHALL yield no worktree, the extension SHALL run the gate without `--worktree`, and for a change past Diff Base capture the gate SHALL fail the verdict evaluation naming the missing worktree — the extension treats that as a normal not-met verdict, never crashing and never treating the degraded run as a same-tree evaluation
