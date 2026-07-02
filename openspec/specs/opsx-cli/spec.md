# opsx-cli Specification

## Purpose
A single `opsx` multitool (gate / models / loop subcommands) consolidating the formerly standalone opsx-* executables behind stable argument and exit-code contracts (ADR-0011), so harnesses and skills integrate against one binary.
## Requirements
### Requirement: Unified Subcommand Dispatch

THE `opsx` command SHALL accept a first positional argument naming a subcommand —
`gate`, `models`, or `loop` — and SHALL dispatch the remaining arguments to that
subcommand's implementation unchanged, preserving its exit code verbatim. Invoking
`opsx` with no subcommand SHALL print usage listing the available subcommands and exit
non-zero.

#### Scenario: Known subcommand dispatches with arguments intact
- **WHEN** `opsx gate <change> --worktree <path>` is run
- **THEN** the gate implementation SHALL receive `<change> --worktree <path>` exactly as if the legacy `opsx-gate <change> --worktree <path>` had been invoked, and `opsx` SHALL exit with the gate's exit code unchanged

#### Scenario: Subcommand exit code is propagated
- **WHEN** a dispatched subcommand exits with code N
- **THEN** `opsx` SHALL exit with code N (no remapping)

#### Scenario: Unknown subcommand is rejected
- **IF** `opsx` is invoked with a first argument that is not `gate`, `models`, or `loop`
- **THEN** `opsx` SHALL print a usage message naming the valid subcommands to standard error and exit non-zero

#### Scenario: Missing subcommand prints usage
- **IF** `opsx` is invoked with no arguments
- **THEN** `opsx` SHALL print usage and exit non-zero

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

THE `opsx` CLI SHALL provide `opsx worktree ensure <change> [--path <p>] [--integration-branch <b>]` and `opsx clean <change> [--force]` as the runtime-owned implementation of the worktree lifecycle (opsx-workflow-schema Worktree Lifecycle Ownership): `ensure` SHALL create the `opsx/<change>` branch + worktree recording the immutable integration-branch merge-base, SHALL reuse an existing branch only when the recorded `Diff Base SHA` is present and an ancestor of `opsx/<change>` (exiting 1 for human repair otherwise), SHALL exit 1 with an actionable message on any creation failure, and SHALL print the locator fields (`Diff Base SHA`, `Worktree Path`, `Integration Branch`) in a stable machine-readable form; `clean` SHALL remove an abandoned change's worktree and branch, refusing a dirty worktree unless `--force` is given, and SHALL be idempotent.

#### Scenario: Ensure creates and records the merge-base
- **WHEN** `opsx worktree ensure <change>` runs and branch `opsx/<change>` does not exist
- **THEN** it SHALL create the branch + worktree from the integration branch, print `WORKTREE-OK created` and a `Diff Base SHA` equal to the integration-branch merge-base, and exit 0

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
operations that write and read role configuration in the layered YAML files. The settable
roles SHALL be `author`, `review`, `impl`, and `author-in-session`; the hyphenated
`author-in-session` token SHALL map to the YAML key `author_in_session` and its value SHALL
be coerced/validated as a boolean (`true`/`false`). The default write target SHALL be the
user layer (`~/.config/opsx/models.yaml`); `--layer user|project` selects the target file.
The project layer SHALL be resolved by: `$OPSX_ROOT` if set, else the nearest ancestor directory
containing an `openspec/` directory, else an error (no write). `set` SHALL create the
target file (and the user layer's parent directory) if absent. `set` writes a single value
(replace semantics; it does NOT merge lists). Writes SHALL be atomic and SHALL preserve
existing comments and key order. `get <role>` SHALL mirror the resolver's read semantics
(layered resolution; empty stdout + exit 0 when unset), and SHALL accept an optional
`--layer user|project` to read back the raw value stored in one specific layer. The YAML
files remain the sole source of truth; this surface is an editor, not a new owner.

#### Scenario: Set writes the role to the default user layer
- **WHEN** `opsx models set author claude-bridge/claude-opus-4-8` is run with no `--layer`
- **THEN** `~/.config/opsx/models.yaml` SHALL be updated so its `author` key equals `claude-bridge/claude-opus-4-8`, and `opsx models get author --layer user` SHALL print that value

#### Scenario: Effective resolution may still be shadowed by a higher layer
- **WHILE** a higher-precedence layer (env, change front-matter, or project) already sets the role
- **WHEN** `opsx models set author <model>` writes the user layer
- **THEN** the user-layer file SHALL contain `<model>`, but a subsequent `opsx models author` (full layered resolution) MAY still print the higher layer's value; only `get author --layer user` is guaranteed to return the just-written value

#### Scenario: Author-in-session is settable
- **WHEN** `opsx models set author-in-session false` is run
- **THEN** the target file's `author_in_session` key SHALL be set to the boolean `false`, and `opsx models author-in-session --json` SHALL resolve `false`

#### Scenario: Layer flag targets the project file
- **WHEN** `opsx models set impl <model> --layer project` is run in a repo with an `openspec/` directory
- **THEN** the project `openspec/opsx-models.yaml` SHALL be updated and the user file SHALL be left unchanged

#### Scenario: Project layer with no discoverable root is rejected
- **IF** `opsx models set <role> <model> --layer project` is run where neither `$OPSX_ROOT` nor an ancestor directory containing `openspec/` can be found
- **THEN** `opsx models` SHALL print an error and exit non-zero without writing any file

#### Scenario: Setting the list-valued review role replaces the whole list
- **WHILE** the `review` role is currently configured with multiple models in the target layer
- **WHEN** `opsx models set review <model>` is run
- **THEN** it SHALL replace the entire `review` value with the single `<model>` AND SHALL surface a warning that the prior multi-model list was replaced (so the multi-model-review footgun is visible); composing a multi-model review list remains a manual YAML edit

#### Scenario: Set creates the target file if absent
- **WHILE** the target layer file does not yet exist
- **WHEN** `opsx models set <role> <model>` is run
- **THEN** it SHALL create the file (and the user layer's parent directory `~/.config/opsx/`) and write the role, leaving a valid YAML document

#### Scenario: Write preserves comments and order
- **WHILE** the target YAML file contains comments and multiple keys
- **WHEN** `opsx models set <role> <model>` updates one key
- **THEN** the other keys, their order, and the file's comments SHALL be preserved

#### Scenario: Write is atomic
- **WHEN** `opsx models set` writes the target file
- **THEN** it SHALL write to a temporary file in the target's own directory and rename it into place only after the update succeeds

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
- **THEN** the effective read SHALL print the built-in boolean default `true` (matching the resolver's `author-in-session` default), WHILE `opsx models get author-in-session --layer user|project` SHALL print nothing when that specific layer does not set the key

#### Scenario: Non-boolean author-in-session value is rejected
- **IF** `opsx models set author-in-session <value>` is given a value that is not `true` or `false`
- **THEN** `opsx models` SHALL print an error and exit non-zero without writing any file

#### Scenario: Invalid role is rejected
- **IF** `opsx models set <role> <model>` is given a role other than `author`, `review`, `impl`, or `author-in-session`
- **THEN** `opsx models` SHALL print an error and exit non-zero without writing any file

#### Scenario: Invalid layer is rejected
- **IF** `opsx models set <role> <model> --layer <x>` is given a layer other than `user` or `project`
- **THEN** `opsx models` SHALL print an error and exit non-zero without writing any file

