# opsx-cli (delta)

## MODIFIED Requirements

### Requirement: Migration Completeness Sweep Command

THE `opsx` CLI SHALL provide a `sweep <change>` subcommand that reads the change's `sweep.txt` declaration (per opsx-workflow-schema Migration Sweep Declaration), greps every git-tracked shipped surface — every git-tracked file outside the excluded OpenSpec workspace (`openspec/**`) and ADR history (`adr/**`) — for the declared patterns, prints each hit as `SWEEP-HIT <pattern> <file>:<line>` on stdout, and exits non-zero when one or more hits exist and zero otherwise, and WHEN the change has no sweep.txt the subcommand SHALL exit zero after printing a one-line notice that no declaration exists, and the subcommand SHALL be deterministic and model-free. THE sweep SHALL run against the change's resolved implementation checkout, resolved exactly as `opsx gate` resolves it — the recorded worktree locator or convention path validating as a git worktree on branch `opsx/<change>` (worktree execution is the only model); WHEN neither validates for a change past Diff Base capture, THE subcommand SHALL fail loudly naming the missing worktree, never silently grepping the integration checkout — and MAY accept an explicit `--worktree <path>` override that is validated loudly (invalid path → immediate hard failure, never a silent fallback); `git ls-files` SHALL enumerate the resolved checkout, never a different tree. WHEN a declared pattern causes a grep error (grep exit status ≥ 2, e.g. a malformed extended regex), THE subcommand SHALL print `SWEEP-ERROR <pattern>` and exit non-zero — a pattern error is a loud validation failure distinct from both a hit and a clean pass, never a silent exit zero.

#### Scenario: Hit fails the sweep
- **WHEN** a declared pattern matches a tracked shipped surface
- **THEN** the command SHALL print the SWEEP-HIT line(s) and exit non-zero

#### Scenario: Clean sweep passes
- **WHEN** no declared pattern matches any tracked shipped surface
- **THEN** the command SHALL exit zero

#### Scenario: Empty declaration is a clean pass
- **WHEN** a sweep.txt exists but contains only comment and blank lines (zero effective patterns)
- **THEN** the command SHALL match nothing and exit zero

#### Scenario: Missing declaration is a soft pass
- **IF** the change directory has no sweep.txt
- **THEN** the command SHALL print a notice and exit zero

#### Scenario: History surfaces never hit
- **WHEN** a declared pattern appears only under openspec/** or adr/**
- **THEN** the command SHALL exit zero

#### Scenario: Sweep targets the resolved implementation checkout
- **WHILE** stale-token fixes have landed only in the worktree
- **WHEN** the sweep runs
- **THEN** it SHALL grep the resolved worktree's tracked files (not the integration root's stale copies), reporting the post-fix state

#### Scenario: Missing worktree fails the sweep loudly
- **WHILE** a change past Diff Base capture has no locator or convention path validating as a git worktree on branch `opsx/<change>`
- **WHEN** `opsx sweep <change>` runs
- **THEN** the command SHALL fail loudly naming the missing worktree and the re-home remedy, never silently evaluating the integration checkout

#### Scenario: Malformed pattern fails loudly
- **IF** a declared pattern is an invalid extended regex (grep errors rather than matching)
- **THEN** the command SHALL print SWEEP-ERROR naming the pattern and exit non-zero, never a silent pass
