# opsx-loop-kickoff Specification

## Purpose
TBD - created by archiving change add-opsx-loop-kickoff. Update Purpose after archive.
## Requirements
### Requirement: Single-command guaranteed loop

THE opsx-loop pi extension SHALL register an `/opsx-loop <change>` command that starts a guaranteed loop: it injects an initial worker turn directed at the openspec-loop skill for the change, and after each subsequent agent turn evaluates `opsx gate` and either continues or stops.

#### Scenario: Starting the loop injects a worker turn
- **WHEN** the user issues `/opsx-loop add-clipboard-extension`
- **THEN** the extension SHALL record the change as the active loop with its turn count reset to zero and SHALL inject one worker turn directed at advancing that change toward a green opsx gate

#### Scenario: Replacing an active loop
- **WHILE** a loop is already active
- **WHEN** the user issues `/opsx-loop` with a new change
- **THEN** the new change SHALL replace the active loop and the turn count SHALL reset to zero

### Requirement: opsx-gate is the deterministic judge

WHILE a loop is active, WHEN a worker turn completes, THE extension SHALL run `opsx gate
<change>` (passing `--worktree <path>` when one is resolved) and treat exit 0 as met and
any non-zero exit as not met, using the gate's report as the directive for the next turn.
THE extension SHALL re-resolve the change's worktree from `review.md` (`Worktree Path`) on
each evaluation rather than only at loop start, so a worktree created after the loop began
(e.g. for a from-scratch change whose `review.md` did not yet exist at kickoff) is picked
up and the gate judges the correct tree. The extension SHALL NOT decide completion from
agent self-assessment.

#### Scenario: Green gate stops the loop
- **WHILE** a loop is active
- **WHEN** a worker turn completes and `opsx gate` exits 0
- **THEN** the extension SHALL clear the active loop, stop injecting turns, and notify the user the change is ready to archive

#### Scenario: Red gate continues the loop
- **WHILE** a loop is active and the turn budget is not exhausted
- **WHEN** a worker turn completes and `opsx gate` exits non-zero
- **THEN** the extension SHALL inject another worker turn carrying the gate's failed-check report as guidance

#### Scenario: Worktree created mid-loop is picked up
- **WHILE** a loop started for a change that had no `review.md` (and thus no resolved worktree) at kickoff
- **WHEN** a later worker turn writes `Worktree Path` into the change's `review.md` and completes
- **THEN** the next evaluation SHALL re-resolve the worktree from `review.md` and run `opsx gate --worktree <path>` against that tree

#### Scenario: Blank or stale worktree path falls back to no-worktree gate
- **WHILE** a loop is active
- **IF** the change's `review.md` has a blank `Worktree Path`, or the recorded path does not point at a valid git worktree
- **THEN** the extension SHALL run `opsx gate <change>` WITHOUT `--worktree` (letting the gate locate or report) rather than crashing, treating the outcome as a normal not-met/met verdict

#### Scenario: Judge command failure is non-fatal
- **WHILE** a loop is active
- **IF** the `opsx gate` command cannot be executed at all
- **THEN** the extension SHALL treat the result as not met, surface an explanatory reason, and continue without crashing the session

### Requirement: Budget from review front-matter

THE extension SHALL bound the loop with a maximum number of continuation turns read from `loop_max_iterations` in the change's `review.md` front-matter, falling back to a built-in default when absent or unparseable.

#### Scenario: Budget exhausted stops and preserves
- **WHILE** a loop is active and the gate is still red
- **IF** the elapsed turn count reaches the budget
- **THEN** the extension SHALL stop injecting turns, clear the active loop, inform the user the budget was exhausted, and NOT remove any worktree

#### Scenario: Default budget when front-matter absent
- **IF** the change's review.md has no parseable `loop_max_iterations`
- **THEN** the extension SHALL apply a built-in default budget without error

### Requirement: Status and clear subcommands

WHEN the user issues `/opsx-loop` with the `status` keyword (or no argument) or with the `clear` directive (or an accepted alias), THE extension SHALL report the active loop's change/turns/budget, or clear the active loop and stop continuing turns, respectively, and SHALL offer `status` and `clear` as argument completions.

#### Scenario: Status reports the active loop
- **WHILE** a loop is active
- **WHEN** the user issues `/opsx-loop status` (or `/opsx-loop` with no change)
- **THEN** the report SHALL show the active change, elapsed turns, the budget, and the last gate reason

#### Scenario: Clear stops the loop
- **WHILE** a loop is active
- **WHEN** the user issues `/opsx-loop clear` (or an alias: stop, off, reset, none, cancel)
- **THEN** the active loop SHALL be removed and no further turns SHALL be injected

### Requirement: Interrupt or error stops the loop

IF a worker turn ends because the user interrupted it or because the turn errored, THEN THE extension SHALL stop the loop and clear the active loop instead of injecting another turn.

#### Scenario: User interrupt halts the loop
- **WHILE** a loop is active
- **IF** the user interrupts the current worker turn
- **THEN** the extension SHALL clear the loop and not inject another turn, informing the user the loop was stopped

#### Scenario: Goal extension is not modified
- **WHEN** the opsx-loop extension is deployed
- **THEN** the `goal` extension's files SHALL be unchanged, and both extensions SHALL operate independently

---

### Requirement: Loop exports resolved role models

WHEN the opsx-loop extension starts a loop for a change, THE extension SHALL resolve the
roles by invoking `opsx models <role> --json --change <name>` (NOT by parsing config
itself, so it matches the gate's resolution) and export `OPSX_AUTHOR_MODEL`,
`OPSX_REVIEW_MODELS`, `OPSX_IMPL_MODEL`, and `OPSX_AUTHOR_IN_SESSION` into the worker turns
it injects, so the skills' authoring and subagent dispatch pick them up. The exported model
values SHALL be provider-resolved (provider-qualified where a provider is configured). The
extension SHALL remain a consumer — it SHALL NOT be the source of truth for the config.

#### Scenario: Models exported on loop start
- **WHEN** the user starts `/opsx-loop <change>` and role models are configured
- **THEN** the injected worker turns SHALL see `OPSX_AUTHOR_MODEL`, `OPSX_REVIEW_MODELS`, `OPSX_IMPL_MODEL`, and `OPSX_AUTHOR_IN_SESSION` set to values resolved WITH `--change <name>` (provider-qualified where a provider is configured, so per-change front-matter is honored and matches the gate)

#### Scenario: Unset config does not break the loop
- **IF** no role models are configured at any layer
- **THEN** the extension SHALL start the loop normally with the variables unset/defaulted, and behavior SHALL match the pre-change loop

#### Scenario: Config survives extension removal
- **WHEN** the opsx-loop extension is removed
- **THEN** the model config and the `opsx models` resolver SHALL remain usable by the bash driver and other harnesses

### Requirement: Argument parsing preserves full input

THE opsx-loop extension's `/opsx-loop` argument parser SHALL NOT silently discard input
after the first whitespace token. WHEN the argument is a recognized leading keyword
(`goal`, `status`, `clear` or an alias, or `models`), it SHALL route to that subcommand
passing the remaining tokens intact; otherwise the first token SHALL be the change name and
any trailing tokens SHALL be ignored ONLY with a surfaced note that they were ignored (so a
mistyped multi-word goal is not silently truncated).

#### Scenario: Multi-token subcommand keeps its arguments
- **WHEN** the user issues `/opsx-loop models set author claude-bridge/claude-opus-4-8`
- **THEN** the parser SHALL route to the `models` subcommand with arguments `set author claude-bridge/claude-opus-4-8` intact, NOT truncate at `models`

#### Scenario: Trailing tokens after a change name are not silently dropped
- **IF** the user issues `/opsx-loop my-change and then some extra words`
- **THEN** the extension SHALL start the loop for `my-change` AND surface a note that the extra words were ignored, rather than silently discarding them

### Requirement: Goal and conversation kickoff

THE opsx-loop extension SHALL support starting a loop from a goal or from the current
conversation via the `goal` leading keyword, for the case where no change exists yet. WHEN
the user issues `/opsx-loop goal <text>`, the extension SHALL treat the ENTIRE remaining
input as the goal (never truncated at the first token). WHEN the user issues `/opsx-loop
goal` with no following text, the extension SHALL start from the current conversation
contents. In either case the extension SHALL record an active loop with no change name yet
(a distilling phase), snapshot the existing active change directories, and inject a worker
turn directing the agent to establish a frozen `intent.md` — reusing an existing change
that already captures the intent, or otherwise distilling the goal or conversation into a
NEW change via openspec-explore/openspec-propose — and then drive that change to a green
`opsx gate` via the openspec-loop skill. After each subsequent agent turn, WHILE still in
the distilling phase, the extension SHALL detect a change directory created since the
snapshot that carries a frozen `intent.md`; once detected it SHALL adopt that change
(resolving its budget and exporting its role models) and thereafter act as the
deterministic-judge loop. IF no such change appears before the turn budget is exhausted,
THEN the extension SHALL stop the loop and notify the user.

#### Scenario: Goal keyword preserves the full multi-word goal
- **WHEN** the user issues `/opsx-loop goal build the clipboard sync with retries`
- **THEN** the extension SHALL start a distilling loop whose goal is the full text `build the clipboard sync with retries`, NOT truncated to `build`

#### Scenario: Bare goal keyword starts from the conversation
- **WHEN** the user issues `/opsx-loop goal` with no following text
- **THEN** the extension SHALL start a distilling loop directed at distilling the current conversation into a frozen intent, with no goal text

#### Scenario: The new change is detected and adopted
- **WHILE** a goal/conversation loop is in its distilling phase
- **WHEN** a change directory not present at kickoff appears with a frozen `intent.md`
- **THEN** the extension SHALL adopt that change as the active loop, resolve its budget and role models, and thereafter run `opsx gate <change>` as the deterministic judge each turn

#### Scenario: No change created within budget stops the loop
- **WHILE** a goal/conversation loop is in its distilling phase
- **IF** no new change directory with a frozen `intent.md` appears before the turn budget is exhausted
- **THEN** the extension SHALL stop the loop and notify the user that no change was created

#### Scenario: Goal offered as completion
- **WHEN** the user requests argument completions for `/opsx-loop`
- **THEN** `goal` SHALL appear alongside `status`, `clear`, and `models`

### Requirement: Stall detection stops the loop

THE extension SHALL stop the loop on a stalled gate: WHILE a loop is active, IF the gate's
normalized failure key is unchanged for a configured number of consecutive evaluations
(default 3) AND no observable progress occurred between them, THEN it SHALL stop injecting
turns, clear the active loop, preserve the worktree, and notify the user that the loop
stalled on a repeating failure so a human can intervene. The normalized failure key SHALL
be the SET of failed-check identifiers (the `check_id` tokens from the `GATE-FAIL` lines),
excluding volatile content (worktree path, commit SHAs, timestamps, free-text messages).
"Observable progress" SHALL mean EITHER a change in the located worktree's HEAD commit OR a
change to the working-tree contents under the change directory (`openspec/changes/<change>/`,
including task-completion edits) since the prior evaluation; any such change SHALL reset the
counter, so in-place authoring iteration that has not yet been committed is not misjudged as
a stall.

#### Scenario: Repeated identical failure with no progress halts the loop
- **WHILE** a loop is active and the budget is not yet exhausted
- **IF** the gate's normalized failed-check-id set is identical for 3 consecutive evaluations AND the worktree HEAD did not advance between them
- **THEN** the extension SHALL stop the loop, preserve the worktree, and notify the user the loop stalled on a repeating failure

#### Scenario: A new commit or uncommitted change-dir edit resets the stall counter
- **WHILE** a loop is active and the same failed-check-id set persists
- **WHEN** the worktree HEAD advances OR the working-tree contents under `openspec/changes/<change>/` change since the prior evaluation
- **THEN** the consecutive-stall counter SHALL reset, so genuine multi-turn progress — committed or still-uncommitted in-place authoring — that leaves the same first failure visible is NOT misjudged as a stall

#### Scenario: A different failure resets the stall counter
- **WHILE** a loop is active
- **WHEN** a later evaluation yields a different normalized failed-check-id set than the previous one
- **THEN** the consecutive-stall counter SHALL reset

#### Scenario: A worktree change resets the stall counter
- **WHILE** a loop is active
- **WHEN** the re-resolved worktree path differs from the prior evaluation's
- **THEN** the consecutive-stall counter SHALL reset, since failures from two different trees are not the "same" failure

### Requirement: Model config subcommand

THE extension SHALL provide a `/opsx-loop models` subcommand: WHEN the user issues
`/opsx-loop models` with a `set`, `get`, or `list` directive, it SHALL shell out to `opsx
models` with the corresponding arguments and report its result, acting purely as a thin
wrapper so the `opsx models` CLI remains the owner of the write. The wrapper SHALL invoke
`opsx models` with the active repository as the working directory (or pass `OPSX_ROOT`) so a
`--layer project` write targets the active repo even when pi's process cwd differs. The
extension SHALL offer `models` as an argument completion.

#### Scenario: Set wrapper delegates to the CLI
- **WHEN** the user issues `/opsx-loop models set author <model>`
- **THEN** the extension SHALL invoke `opsx models set author <model>` and report success or the CLI's error, without writing any config file itself

#### Scenario: List wrapper shows resolved roles
- **WHEN** the user issues `/opsx-loop models list`
- **THEN** the extension SHALL invoke `opsx models list` and present its output

#### Scenario: Project-layer write targets the active repo
- **WHEN** the user issues `/opsx-loop models set <role> <model> --layer project`
- **THEN** the wrapper SHALL invoke `opsx models` with the active repo cwd (or `OPSX_ROOT`) so the project file resolved is the active repo's `openspec/opsx-models.yaml`, not a directory derived from pi's process cwd

#### Scenario: Bare models lists the resolved roles
- **WHEN** the user issues `/opsx-loop models` with no further directive
- **THEN** the extension SHALL invoke `opsx models list` and present its output

#### Scenario: Models offered as completion
- **WHEN** the user requests argument completions for `/opsx-loop`
- **THEN** `models` SHALL appear alongside `goal`, `status`, and `clear`

