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

### Requirement: Model Config Write Surface

THE `opsx models` subcommand SHALL provide `set <role> <value>`, `get <role>`, and `list`
operations that write and read role configuration in the user YAML file. The settable
roles SHALL be `author`, `review`, `impl`, and `author-in-session`; the hyphenated
`author-in-session` token SHALL map to the YAML key `author_in_session` and its value SHALL
be coerced/validated as a boolean (`true`/`false`). The sole write target SHALL be the
user layer (`~/.config/opsx/models.yaml`); `--layer user` remains accepted as an explicit
spelling of the default, and `--layer project` SHALL be REJECTED with an error naming the
project-layer removal and the front-matter alternative (per the opsx-model-config
Layered Resolution Order), exiting non-zero without writing any file. `set` SHALL create the
target file (and its parent directory) if absent. `set` writes a single value
(replace semantics; it does NOT merge lists). Writes SHALL be atomic and SHALL preserve
existing comments and key order. `get <role>` SHALL mirror the resolver's read semantics
(layered resolution; empty stdout + exit 0 when unset), and SHALL accept an optional
`--layer user` to read back the raw value stored in the user layer. The YAML
file remains the sole source of truth; this surface is an editor, not a new owner.

#### Scenario: Set writes the role to the default user layer
- **WHEN** `opsx models set author claude-bridge/claude-opus-4-8` is run with no `--layer`
- **THEN** `~/.config/opsx/models.yaml` SHALL be updated so its `author` key equals `claude-bridge/claude-opus-4-8`, and `opsx models get author --layer user` SHALL print that value

#### Scenario: Effective resolution may still be shadowed by a higher layer
- **WHILE** a higher-precedence layer (env or change front-matter) already sets the role
- **WHEN** `opsx models set author <model>` writes the user layer
- **THEN** the user-layer file SHALL contain `<model>`, but a subsequent `opsx models author` (full layered resolution) MAY still print the higher layer's value; only `get author --layer user` is guaranteed to return the just-written value

#### Scenario: Author-in-session is settable
- **WHEN** `opsx models set author-in-session false` is run
- **THEN** the target file's `author_in_session` key SHALL be set to the boolean `false`, and `opsx models author-in-session --json` SHALL resolve `false`

#### Scenario: Project layer write is rejected with the removal message
- **IF** `opsx models set <role> <model> --layer project` is run
- **THEN** `opsx models` SHALL print an error naming the project-layer removal and the review.md front-matter alternative, and SHALL exit non-zero without writing any file

#### Scenario: Setting the list-valued review role replaces the whole list
- **WHILE** the `review` role is currently configured with multiple models in the target layer
- **WHEN** `opsx models set review <model>` is run
- **THEN** the stored `review` value SHALL be exactly `<model>` (full replace; no merge with the prior list)

#### Scenario: Failed write leaves the original intact
- **IF** the temp write, the YAML update, or the rename fails
- **THEN** `opsx models` SHALL exit non-zero, leave the prior target file byte-for-byte unchanged, and remove any temporary file it created

#### Scenario: List reports resolved roles with sources
- **WHEN** `opsx models list` is run
- **THEN** it SHALL print each role (`author`, `review`, `impl`, `author-in-session`) with its resolved value and the layer that supplied it

#### Scenario: Get of an unset scalar role is empty
- **WHEN** `opsx models get <role>` is run for `author`, `review`, or `impl` and no layer configures the role
- **THEN** it SHALL print nothing to standard output and exit 0

#### Scenario: Get of author-in-session reflects its boolean default
- **WHEN** `opsx models get author-in-session` is run and no layer configures it
- **THEN** the effective read SHALL print the built-in boolean default `true` (matching the resolver's `author-in-session` default), WHILE `opsx models get author-in-session --layer user` SHALL print nothing when that specific layer does not set the key

#### Scenario: Non-boolean author-in-session value is rejected
- **IF** `opsx models set author-in-session <value>` is given a value that is not `true` or `false`
- **THEN** `opsx models` SHALL print an error and exit non-zero without writing any file

#### Scenario: Invalid role is rejected
- **IF** `opsx models set <role> <model>` is given a role other than `author`, `review`, `impl`, or `author-in-session`
- **THEN** `opsx models` SHALL print an error and exit non-zero without writing any file

#### Scenario: Invalid layer is rejected
- **IF** `opsx models set <role> <model> --layer <x>` is given a layer other than `user` (the retired `project` value carries its own rejection scenario above)
- **THEN** `opsx models` SHALL print an error and exit non-zero without writing any file

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

#### Scenario: Change without review.md or branch prints placeholders, never crashes
- **WHILE** a non-archive change directory has no `review.md` (e.g. a from-scratch change still in its distilling phase) so its Scale is undeclared and no `opsx/<change>` branch exists
- **WHEN** `opsx status` reports that change
- **THEN** it SHALL print a stable placeholder (for example `—`/`unknown`) for the undeclared Scale, worktree, `loop_hold`, and commits-behind fields rather than erroring, and SHALL still exit 0, since `opsx status` is a view that must never crash on an incomplete change

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
