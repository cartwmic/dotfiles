<!-- authored: delegate spec-consolidation -->
# Capability: opsx-cli

Delta for simplify-and-parallelize-opsx-workflow: add the read-only `opsx status` fleet
view (A5) and a deterministic multi-dir integration-commit detector (A2), and harden the
worktree-ensure reuse/refuse rules (A4). All additions are deterministic and model-free.
The modified requirement restates its full content per the MODIFIED-delta rule.

## MODIFIED Requirements

### Requirement: Worktree Lifecycle Commands

THE `opsx` CLI SHALL provide `opsx worktree ensure <change> [--path <p>] [--integration-branch <b>]` and `opsx clean <change> [--force]` as the runtime-owned implementation of the worktree lifecycle (opsx-workflow-schema Worktree Lifecycle Ownership): `ensure` SHALL create the `opsx/<change>` branch + worktree recording the immutable integration-branch merge-base, SHALL REUSE an existing worktree IF AND ONLY IF it validates on branch `opsx/<change>` (the `opsx_wt_valid_for_change` check: the path is a git worktree checked out on branch `opsx/<change>`) AND the recorded `Diff Base SHA` is present and an ancestor of `opsx/<change>`, SHALL otherwise REFUSE LOUDLY (exit 1 with an actionable human-repair message) and SHALL NEVER auto-delete or silently recreate an existing worktree, SHALL exit 1 with an actionable message on any creation failure, and SHALL print the locator fields (`Diff Base SHA`, `Worktree Path`, `Integration Branch`) in a stable machine-readable form; `clean` SHALL remove an abandoned change's worktree and branch, refusing a dirty worktree unless `--force` is given, and SHALL be idempotent.

#### Scenario: Ensure creates and records the merge-base
- **WHEN** `opsx worktree ensure <change>` runs and branch `opsx/<change>` does not exist
- **THEN** it SHALL create the branch + worktree from the integration branch, print `WORKTREE-OK created` and a `Diff Base SHA` equal to the integration-branch merge-base, and exit 0

#### Scenario: Reuse only when valid on the change branch
- **WHILE** a worktree already exists for the change AND it validates on branch `opsx/<change>` with a recorded `Diff Base SHA` present and an ancestor of `opsx/<change>`
- **WHEN** `opsx worktree ensure <change>` runs
- **THEN** it SHALL reuse that worktree, preserve the recorded `Diff Base SHA`, and SHALL NOT recreate or delete it

#### Scenario: Refuse loudly and never auto-delete on a mismatched worktree
- **IF** an existing worktree does NOT validate on branch `opsx/<change>` (wrong branch, not a git worktree, or the recorded base is absent or not an ancestor)
- **THEN** `opsx worktree ensure` SHALL exit 1 with an actionable human-repair message and SHALL NEVER auto-delete, reset, or silently recreate the existing worktree

#### Scenario: Reuse halts without a valid recorded base
- **IF** branch `opsx/<change>` exists but review.md has no recorded `Diff Base SHA`, or the recorded base is not an ancestor of `opsx/<change>`
- **THEN** `opsx worktree ensure` SHALL exit 1 with a halt-for-human-repair message and SHALL NOT re-record a base

#### Scenario: Creation failure aborts
- **IF** worktree creation fails (path conflict, detached HEAD without `--integration-branch`, permissions, disk)
- **THEN** `opsx worktree ensure` SHALL exit 1 with an actionable message so the caller does not proceed to implementation tasks

#### Scenario: Clean refuses dirty without force and is idempotent
- **IF** the change's worktree has uncommitted changes and `--force` is absent
- **THEN** `opsx clean <change>` SHALL refuse with exit 1; WHEN `--force` is given it SHALL remove the worktree and delete branch `opsx/<change>`; WHEN nothing remains to clean it SHALL exit 0

## ADDED Requirements

### Requirement: Status Fleet View

THE `opsx` CLI SHALL provide `opsx status` as a READ-ONLY, deterministic, model-free fleet view that scans the non-archive change directories under `openspec/changes/*` and, per change, prints: the declared Scale; the gate red/green summary plus the earliest failing check; the worktree path and its validity on branch `opsx/<change>`; the `loop_hold` state and its reason; and the Diff Base SHA staleness expressed as commits-behind-`main`. `opsx status` SHALL have NO side effects (no file, branch, or worktree creation or mutation), SHALL make NO model calls, and SHALL exit 0 always — it is a view, not a gate.

#### Scenario: Per-change fleet summary printed
- **WHEN** `opsx status` runs with one or more non-archive changes under `openspec/changes/`
- **THEN** it SHALL print, for each change, its Scale, gate red/green + earliest failing check, worktree path + validity on branch `opsx/<change>`, `loop_hold` + reason, and Diff Base commits-behind-`main` staleness

#### Scenario: Status has no side effects and always exits 0
- **WHEN** `opsx status` runs
- **THEN** it SHALL NOT create or mutate any file, branch, or worktree, SHALL NOT invoke any model, and SHALL exit 0 regardless of any change's gate being red

#### Scenario: Archive directory excluded
- **WHILE** `openspec/changes/archive/` contains archived changes
- **WHEN** `opsx status` scans the fleet
- **THEN** it SHALL scan only the non-archive change directories and SHALL NOT report archived changes

### Requirement: Multi-Dir Integration Commit Detector

THE `opsx` CLI SHALL provide a deterministic detector that flags any integration-checkout commit touching more than one `openspec/changes/<change>/` directory, as an advisory detection surface backstopping the path-scoped-commit discipline (detection, not prevention), computed from git plumbing with no model judgment.

#### Scenario: Multi-dir commit is flagged
- **IF** an integration-checkout commit touches paths under two or more distinct `openspec/changes/<change>/` directories
- **THEN** the detector SHALL flag that commit (naming it and the touched change directories) as an advisory finding

#### Scenario: Single-dir commit is not flagged
- **WHILE** a commit touches paths within at most one `openspec/changes/<change>/` directory
- **WHEN** the detector runs
- **THEN** it SHALL NOT flag that commit

#### Scenario: Detection is advisory, not prevention
- **WHEN** the detector flags a multi-dir commit
- **THEN** it SHALL surface the finding as advisory and SHALL NOT by itself block a commit or fail the gate, per the detection-not-prevention posture
