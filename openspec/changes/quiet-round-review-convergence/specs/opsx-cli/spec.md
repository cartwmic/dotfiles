# opsx-cli (delta)

## ADDED Requirements

### Requirement: Migration Completeness Sweep Command

THE `opsx` CLI SHALL provide a `sweep <change>` subcommand that reads the change's `sweep.txt` declaration (per opsx-workflow-schema Migration Sweep Declaration), greps every git-tracked file outside the excluded history surfaces for the declared patterns, prints each hit as `SWEEP-HIT <pattern> <file>:<line>` on stdout, and exits non-zero when one or more hits exist and zero otherwise, and WHEN the change has no sweep.txt the subcommand SHALL exit zero after printing a one-line notice that no declaration exists, and the subcommand SHALL be deterministic and model-free.

#### Scenario: Hit fails the sweep
- **WHEN** a declared pattern matches a tracked shipped surface
- **THEN** the command SHALL print the SWEEP-HIT line(s) and exit non-zero

#### Scenario: Clean sweep passes
- **WHEN** no declared pattern matches any tracked shipped surface
- **THEN** the command SHALL exit zero

#### Scenario: Missing declaration is a soft pass
- **IF** the change directory has no sweep.txt
- **THEN** the command SHALL print a notice and exit zero

#### Scenario: History surfaces never hit
- **WHEN** a declared pattern appears only under openspec/changes/** or adr/**
- **THEN** the command SHALL exit zero
