# opsx-cli Specification

## Purpose
A single `opsx` multitool (gate / models / loop subcommands) consolidating the formerly standalone opsx-* executables behind stable argument and exit-code contracts (ADR-0011), so harnesses and skills integrate against one binary.
## Requirements
### Requirement: Unified Subcommand Dispatch

THE `opsx` command SHALL accept a first positional argument naming a subcommand — `gate`, `models`, `status`, `archive-check`, `loop`, `worktree`, `clean`, or `sweep` — and SHALL dispatch the remaining arguments to that subcommand's implementation unchanged, preserving its exit code verbatim. Invoking `opsx` with no subcommand SHALL print usage listing the available subcommands and exit non-zero.

#### Scenario: Known subcommand dispatches with arguments intact
- **WHEN** `opsx gate <change> --worktree <path>` is run
- **THEN** the gate implementation SHALL receive `<change> --worktree <path>` exactly as if the legacy `opsx-gate <change> --worktree <path>` had been invoked, and `opsx` SHALL exit with the gate's exit code unchanged

#### Scenario: Subcommand exit code is propagated
- **WHEN** a dispatched subcommand exits with code N
- **THEN** `opsx` SHALL exit with code N (no remapping)

#### Scenario: Unknown subcommand is rejected
- **IF** `opsx` is invoked with a first argument that is not one of the enumerated subcommands
- **THEN** `opsx` SHALL print a usage message naming the valid subcommands to standard error and exit non-zero

#### Scenario: Missing subcommand prints usage
- **IF** `opsx` is invoked with no arguments
- **THEN** `opsx` SHALL print usage and exit non-zero

#### Scenario: Sweep dispatches
- **WHEN** `opsx sweep <change>` is run
- **THEN** the sweep implementation SHALL receive `<change>` and `opsx` SHALL exit with the sweep's exit code unchanged

### Requirement: Hard Cutover No Legacy Entrypoints

THE consolidation SHALL install exactly one executable, `opsx`, and SHALL NOT install the
standalone `opsx-gate`, `opsx-models`, or `opsx-loop` executables. All in-repo callers
(canonical skills, schema/templates, pi extensions, tests, manifests) SHALL invoke the
subcommand form (`opsx gate` / `opsx models` / `opsx loop`).

#### Scenario: Legacy executables are absent after deploy
- **WHEN** the change is deployed via `chezmoi apply`
- **THEN** `~/.local/bin/opsx` SHALL exist and be executable, and `~/.local/bin/opsx-gate`, `~/.local/bin/opsx-models`, and `~/.local/bin/opsx-loop` SHALL NOT exist

#### Scenario: No live caller references a legacy executable name
- **WHEN** the caller surface is scanned for legacy executable invocations — specifically the paths `dot_local/share/agent-harness/**`, `dot_local/share/openspec/schemas/**`, `dot_pi/agent/extensions/**`, `tests/**`, `docs/**`, and the root `openspec/opsx-gates.yaml` manifest — for the tokens `opsx-gate` and `opsx-models` and the `opsx-loop` bash-driver invocation
- **THEN** every match SHALL use the `opsx <subcommand>` form, with these explicit exemptions: the substrings inside capability/identifier names (`opsx-gate-enforcement`, `opsx-model-config`, `opsx-loop-orchestration`, `opsx-loop-kickoff`, `opsx-skill-integration`, `opsx-workflow-schema`, `opsx-post-impl-review`), the config filenames `opsx-gates.yaml` and `opsx-models.yaml`, and the `opsx-loop` pi-extension directory name + its `/opsx-loop` slash command (none of which are executable invocations)

#### Scenario: Spec-of-record and history are out of scan scope
- **WHEN** the legacy-token scan runs during verify
- **THEN** it SHALL NOT scan `openspec/specs/**`, `openspec/changes/**`, or `adr/**` — the capability specs are migrated to the subcommand form by this change's MODIFIED deltas (applied at archive, not in the working tree during the gate), and `openspec/changes/**` + `adr/**` are spec/history records, not executable callers

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

### Requirement: Status Fleet View

THE `opsx` CLI SHALL provide `opsx status` as a READ-ONLY, deterministic, model-free fleet view that scans the non-archive change directories under `openspec/changes/*` and, per change, prints: the declared Scale; the gate red/green summary plus the earliest failing check; the worktree path and its validity on branch `opsx/<change>`; the `loop_hold` state and its reason; and the Diff Base SHA staleness expressed as commits behind the resolved integration branch (per `Integration Branch Resolution`), never a hardcoded branch literal. `opsx status` SHALL have NO side effects (no file, branch, or worktree creation or mutation), SHALL make NO model calls, and SHALL exit 0 always — it is a view, not a gate.

#### Scenario: Per-change fleet summary printed
- **WHEN** `opsx status` runs with one or more non-archive changes under `openspec/changes/`
- **THEN** it SHALL print, for each change, its Scale, gate red/green + earliest failing check, worktree path + validity on branch `opsx/<change>`, `loop_hold` + reason, and Diff Base staleness as commits behind the resolved integration branch

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

#### Scenario: Non-main default branch reports staleness correctly
- **WHILE** the repository's integration branch resolves to a name other than `main` (e.g. `trunk`)
- **WHEN** `opsx status` computes Diff Base commits-behind staleness
- **THEN** it SHALL count against the resolved branch and SHALL NOT print a placeholder merely because no `main` branch exists

### Requirement: Multi-Dir Integration Commit Detector

THE `opsx` CLI SHALL provide a deterministic detector that flags any integration-checkout commit touching more than one `openspec/changes/<change>/` directory, as an advisory detection surface backstopping the path-scoped-commit discipline (detection, not prevention), computed from git plumbing with no model judgment; the detector's scan range SHALL terminate at the resolved integration branch (per `Integration Branch Resolution`), never a hardcoded branch literal, so the detector functions in repositories whose integration branch is not named `main`.

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

#### Scenario: Detector runs in a non-main repository
- **WHILE** the repository's integration branch resolves to a name other than `main`
- **WHEN** the detector scans `<Diff Base SHA>..<resolved branch>`
- **THEN** it SHALL flag multi-dir commits in that range rather than silently skipping because no `main` branch exists

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

### Requirement: Integration Branch Resolution

THE `opsx` CLI SHALL resolve the integration branch through a single deterministic helper wherever a check compares against the integration branch, with resolution order (first hit wins): (1) the change's committed review.md `**Integration Branch:**` locator field when a change context exists and the field, after trimming surrounding whitespace, is non-empty and is not the shipped placeholder sentinel `<detected-at-capture>` (the single token the template ships and the resolver recognizes — clarify C1); (2) the short name of `git symbolic-ref refs/remotes/origin/HEAD`; (3) a local branch named `main`; (4) a local branch named `master`; and IF no step resolves, THEN blocking invokers (gate and archive/land checks) SHALL fail loudly with a named error identifying the unresolvable integration branch rather than silently assuming any default, WHILE the read-only `opsx status` view SHALL instead degrade to its stable placeholder fields and still exit 0 (clarify C3). The resolver SHALL be pure git plumbing plus file reads — no model call, no configuration-file override key.

#### Scenario: Locator field wins when present
- **WHILE** the change's committed review.md carries an `**Integration Branch:**` value that, after whitespace trim, is non-empty and is not the `<detected-at-capture>` sentinel
- **WHEN** an integration-branch-dependent check resolves the branch for that change
- **THEN** the resolver SHALL return the locator field's value without consulting later steps

#### Scenario: origin/HEAD symbolic-ref resolves when no locator applies
- **WHILE** no change-scoped locator value applies AND `git symbolic-ref refs/remotes/origin/HEAD` resolves
- **WHEN** the resolver runs
- **THEN** it SHALL return the symbolic-ref's short branch name

#### Scenario: master-only repo resolves to master
- **WHILE** no locator value applies, no `refs/remotes/origin/HEAD` symbolic-ref resolves, no local `main` branch exists, and a local `master` branch exists
- **WHEN** the resolver runs
- **THEN** it SHALL return `master`

#### Scenario: Unresolvable branch fails loudly in blocking checks
- **IF** no resolution step yields a branch
- **THEN** a blocking invoker (gate or archive/land check) SHALL fail with a named error stating the integration branch could not be resolved, and SHALL NOT proceed against a guessed branch

#### Scenario: Unresolvable branch degrades to placeholder in the status view
- **IF** no resolution step yields a branch
- **WHEN** `opsx status` computes its commits-behind staleness field
- **THEN** it SHALL print its stable placeholder for that field and still exit 0, per the view-never-crashes posture (clarify C3)

#### Scenario: Resolution is deterministic and model-free
- **WHEN** the resolver runs
- **THEN** it SHALL be computed solely from the committed locator field and git plumbing, with no model call and no environment-dependent guessing beyond the declared order

