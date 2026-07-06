# opsx-loop Specification

## Purpose
TBD - created by archiving change simplify-and-parallelize-opsx-workflow. Update Purpose after archive.
## Requirements
### Requirement: Single-command guaranteed loop

THE opsx-loop pi extension SHALL register an `/opsx-loop <change>` command that starts a guaranteed loop: it FIRST evaluates `opsx gate <change>` and, IF the gate is already green, reports the change ready to archive WITHOUT arming a loop or injecting a worker turn; otherwise it injects an initial worker turn directed at the openspec-loop skill for the change, and after each subsequent agent turn evaluates `opsx gate` and either continues or stops.

#### Scenario: Starting the loop injects a worker turn
- **WHEN** the user issues `/opsx-loop add-clipboard-extension` for a change whose gate is not yet green
- **THEN** the extension SHALL record the change as the active loop with its turn count reset to zero and SHALL inject one worker turn directed at advancing that change toward a green opsx gate

#### Scenario: Kickoff on an already-green change does not loop
- **WHEN** the user issues `/opsx-loop <change>` for a change whose `opsx gate` already exits 0
- **THEN** the extension SHALL NOT arm a loop or inject a worker turn, and SHALL notify the user that the change already passes the gate and is ready to archive, so re-issuing a kickoff on a finished change cannot spin it in an endless loop

#### Scenario: Replacing an active loop
- **WHILE** a loop is already active
- **WHEN** the user issues `/opsx-loop` with a new change
- **THEN** the new change SHALL replace the active loop and the turn count SHALL reset to zero

#### Scenario: Injected directives instruct autonomous operation
- **WHEN** the extension injects any loop directive (worker or distill)
- **THEN** the directive SHALL instruct the agent to run autonomously — not to pause for clarifying questions or user confirmation, to make the most reasonable decision from the intent/specs/conversation and record assumptions in the change artifacts, and to ask ONLY when truly blocked (genuinely un-inferable intent, or an irreversible/destructive action outside the change)

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
- **THEN** the extension SHALL inject another worker turn carrying the gate's failed-check report as guidance, framed as a CONTINUATION of the existing change (instructing the agent to resume that change and NOT to start a new loop, create another change, or restart the workflow from proposal)

#### Scenario: Worktree created mid-loop is picked up
- **WHILE** a loop started for a change that had no `review.md` (and thus no resolved worktree) at kickoff
- **WHEN** a later worker turn writes `Worktree Path` into the change's `review.md` and completes
- **THEN** the next evaluation SHALL re-resolve the worktree from `review.md` and run `opsx gate --worktree <path>` against that tree

#### Scenario: Blank or stale worktree path probes the convention fallback before degrading
- **WHILE** a loop is active
- **IF** the change's `review.md` has a blank `Worktree Path`, or the recorded path does not point at a valid git worktree
- **THEN** the extension SHALL first probe the canonical convention path (per the worktree-resolution-fallback requirement) and use it when valid; only when that probe also fails SHALL it run `opsx gate <change>` WITHOUT `--worktree` (letting the gate locate or report) rather than crashing, treating the outcome as a normal not-met/met verdict

#### Scenario: Judge command failure is non-fatal
- **WHILE** a loop is active
- **IF** the `opsx gate` command cannot be executed at all
- **THEN** the extension SHALL treat the result as not met, surface an explanatory reason, and continue without crashing the session

### Requirement: Budget from review front-matter

THE extension SHALL bound the loop with a maximum number of continuation turns read from `loop_max_iterations` in the change's `review.md` front-matter. WHEN `loop_max_iterations` is absent or unparseable the budget SHALL be unset, meaning the loop is unbounded by turn count (it then stops only on a green gate, stall detection, user abort, or manual clear). No built-in numeric default SHALL be applied.

#### Scenario: Budget exhausted stops and preserves
- **WHILE** a loop is active, a budget is configured, and the gate is still red
- **IF** the elapsed turn count reaches the configured budget
- **THEN** the extension SHALL stop injecting turns, clear the active loop, inform the user the budget was exhausted, and NOT remove any worktree

#### Scenario: Unset budget runs unbounded
- **IF** the change's review.md has no parseable `loop_max_iterations`
- **THEN** the extension SHALL treat the budget as unset and SHALL NOT stop the loop on any turn count, relying on the green gate, stall detection, abort, or manual clear to terminate

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
contents. Goal/conversation kickoff SHALL NEVER latch onto a pre-existing change: the
explicit `/opsx-loop <change-name>` spelling is the SOLE latch path for existing changes,
and the extension SHALL NOT perform any goal-text-to-change-name matching (exact or
substring) — successor goals naturally reference predecessor change names as context,
making text matching a false-latch hazard. In either goal form the extension SHALL record
an active loop with no change name yet (a distilling phase), snapshot the existing active
change directories, and inject a distill directive directing the agent to DRAFT an
`intent.md` baseline into a NEW change via openspec-explore/openspec-propose — WITHOUT
proceeding to implementation. The distill directive SHALL include a deterministic
active-change inventory — the names of existing change directories carrying a committed
`intent.md`, with cheap front-matter status, produced by directory listing and
front-matter parsing ONLY (no gate executions, no model calls) — and SHALL instruct the
agent: if an inventoried change already captures the goal, do NOT create a new change;
announce that fact, advise the user to arm it with `/opsx-loop <name>`, and stop. The
distill directive's autonomy text SHALL be distill-scoped — draft the intent
autonomously, do NOT implement, STOP after announcing — and SHALL NOT carry the
drive-to-green autonomy text used by worker/continuation directives. After each
subsequent agent turn, WHILE still in the distilling phase, the extension SHALL detect a
change directory created since the snapshot that carries an `intent.md`; once detected it
SHALL NOT silently adopt the agent-authored baseline: it SHALL stop the distilling loop
and notify the user that the change is PAUSED for intent confirmation (one-shot human
confirm, ADR-0014) — the user reviews/edits `intent.md` and arms the deterministic-judge
loop explicitly with `/opsx-loop <change>` (which resolves the budget and exports role
models). IF a budget is configured AND no such change appears before it is exhausted,
THEN the extension SHALL stop the loop and notify the user. INDEPENDENT of the budget,
the extension SHALL bound the distilling phase with a stall guard: IF no change-directory
progress occurs (no new change directory appears since the prior distilling turn) for a
configured number of consecutive turns (default 3), THEN it SHALL stop the loop and
notify the user. The stall baseline SHALL be seeded at arm time from the kickoff
change-directory snapshot, so the first distilling turn is counted and the guard fires
after exactly the configured number of no-progress turns (not one extra
baseline-initialization turn), keeping the stall notification's stated turn count
truthful.

#### Scenario: Goal keyword preserves the full multi-word goal
- **WHEN** the user issues `/opsx-loop goal build the clipboard sync with retries`
- **THEN** the extension SHALL start a distilling loop whose goal is the full text `build the clipboard sync with retries`, NOT truncated to `build`

#### Scenario: Bare goal keyword starts from the conversation
- **WHEN** the user issues `/opsx-loop goal` with no following text
- **THEN** the extension SHALL start a distilling loop directed at distilling the current conversation into a frozen intent, with no goal text

#### Scenario: Goal mode never latches a pre-existing change
- **WHILE** a pre-existing change directory with a committed `intent.md` passes the opsx gate
- **WHEN** the user issues `/opsx-loop goal <text>` for unrelated work
- **THEN** the extension SHALL start an ordinary distilling loop, SHALL NOT arm onto or report the green bystander change as the loop target, and SHALL NOT compare the goal text against change names

#### Scenario: Distill directive carries the active-change inventory
- **WHILE** change directories with committed `intent.md` files exist at kickoff
- **WHEN** the extension injects the distill directive
- **THEN** the directive SHALL list those change names with cheap front-matter status (derived without gate runs or model calls) and SHALL instruct the agent to stop and advise `/opsx-loop <name>` instead of creating a duplicate change when one already captures the goal

#### Scenario: Distill directive autonomy is distill-scoped
- **WHEN** the extension injects the distill directive
- **THEN** its autonomy text SHALL instruct drafting the intent autonomously, NOT implementing, and STOPPING after the announcement, and SHALL NOT contain the drive-to-green "keep going / the gate is the arbiter of done" text carried by worker directives

#### Scenario: The new change is detected and paused for intent confirmation
- **WHILE** a goal/conversation loop is in its distilling phase
- **WHEN** a change directory not present at kickoff appears with an `intent.md`
- **THEN** the extension SHALL stop the distilling loop, SHALL notify the user that the change awaits intent confirmation (naming the change and the intent.md path and instructing `/opsx-loop <change>` to arm), and SHALL NOT inject further turns or run the gate until the user arms the loop explicitly

#### Scenario: No change created within a configured budget stops the loop
- **WHILE** a goal/conversation loop is in its distilling phase AND a budget is configured
- **IF** no new change directory with a frozen `intent.md` appears before the configured budget is exhausted
- **THEN** the extension SHALL stop the loop and notify the user that no change was created

#### Scenario: A stalled distilling phase stops the loop after exactly the configured turns
- **WHILE** a goal/conversation loop is in its distilling phase AND the budget is unset (unbounded)
- **IF** no new change directory appears for the configured number of consecutive turns (default 3), counted from the first distilling turn because the stall baseline was seeded at arm time
- **THEN** the extension SHALL stop the loop after exactly that many no-progress turns and notify the user (rather than re-injecting the distill directive forever, and rather than consuming an extra baseline-initialization turn), advising that an already-captured intent be driven via `/opsx-loop <change>` or archived

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
a stall. HOWEVER, WHILE the blocking failure key is exactly the doneness check (`doneness`)
and no other check is failing, the extension SHALL classify the doneness state by parsing
`doneness.md` **directly** (NOT by reading the gate's free-text message): a `not` verdict, or
an absent/unparseable file, activates the gap-set progress signal below; a `satisfied`
verdict failing only on staleness, mismatched baseline, or provenance uses the ordinary
HEAD/content progress signal above (it is re-judged next turn). Under the gap-set signal,
"observable progress" SHALL be defined as the normalized doneness **gap set** (unmet-gap
phrases parsed from `doneness.md`, with an absent/unparseable file mapped to the empty-set
sentinel) **strictly shrinking against the running minimum**: the extension SHALL track
`min_gaps`, the smallest gap set observed since the current doneness-blocked streak began,
and SHALL count progress ONLY when the new gap set is a NON-EMPTY proper subset of `min_gaps`
with strictly fewer members, updating `min_gaps` on each such reduction. The empty-set
sentinel (an absent or unparseable `doneness.md`) SHALL NOT count as progress and SHALL NOT
overwrite `min_gaps`, so a transient parse flake cannot manufacture a spurious reduction to
the empty set; it advances the stall counter like any non-reducing observation. Any gap set
that is not a NON-EMPTY proper subset of `min_gaps` — growth, equal cardinality with swapped
members, the empty-set sentinel, an oscillation
down-swing to a previously-seen set, or a reword to the same normalized membership — SHALL
NOT count as progress and SHALL advance the stall counter, so an agent that churns files or
oscillates gaps without monotonically closing them trips the stall instead of looping
forever under an unbounded budget. The extension SHALL reset `min_gaps` (and the counter)
only when the failed-check-id set changes, the located worktree changes, or the gate goes
green.

#### Scenario: Repeated identical failure with no progress halts the loop
- **WHILE** a loop is active and the budget is not yet exhausted
- **IF** the gate's normalized failed-check-id set is identical for 3 consecutive evaluations AND the worktree HEAD did not advance between them
- **THEN** the extension SHALL stop the loop, preserve the worktree, and notify the user the loop stalled on a repeating failure

#### Scenario: A new commit or uncommitted change-dir edit resets the stall counter
- **WHILE** a loop is active, the same failed-check-id set persists, AND that set is NOT exactly `{doneness}` with a `not`/absent/unparseable verdict (the doneness case uses the gap-set ratchet below, not content/HEAD)
- **WHEN** the worktree HEAD advances OR the working-tree contents under `openspec/changes/<change>/` change since the prior evaluation
- **THEN** the consecutive-stall counter SHALL reset, so genuine multi-turn progress — committed or still-uncommitted in-place authoring — that leaves the same first failure visible is NOT misjudged as a stall

#### Scenario: A stale verdict is re-judged before the doneness stall check
- **WHILE** the only failing check is `doneness` and a prior verdict's reviewed range no longer matches the current HEAD
- **WHEN** the orchestration evaluates the turn
- **THEN** it SHALL re-dispatch the doneness judge to produce a fresh verdict BEFORE the stall detector classifies the state, so the gap-set comparison always sees a fresh verdict, and a HEAD advance alone on a doneness-blocked turn SHALL NOT by itself reset the stall counter

#### Scenario: Doneness gap set is the progress signal on a doneness-blocked turn
- **WHILE** a loop is active and the only failing check is `doneness` with a `not`/absent/unparseable verdict (classified by parsing `doneness.md` directly, absent/unparseable mapped to the empty-set sentinel)
- **IF** the doneness gap set does not drop below `min_gaps` for 3 consecutive evaluations
- **THEN** the consecutive-stall counter SHALL advance even if change-directory contents changed between evaluations, and the extension SHALL stop the loop on reaching the limit

#### Scenario: A non-empty gap set below the running minimum resets the stall counter
- **WHILE** a loop is active and the only failing check is `doneness` with a `not`/absent/unparseable verdict
- **WHEN** the doneness gap set is NON-EMPTY and a proper subset of `min_gaps` (the smallest set seen since the streak began) with strictly fewer members
- **THEN** the extension SHALL update `min_gaps` to the new set and reset the consecutive-stall counter, since the judge recorded a genuine monotonic reduction of the intent gaps

#### Scenario: The empty-set sentinel does not reset the stall counter
- **WHILE** a loop is active and the only failing check is `doneness` with an absent/unparseable verdict (mapped to the empty-set sentinel)
- **WHEN** the extension classifies the turn's progress
- **THEN** the empty-set sentinel SHALL NOT count as progress and SHALL NOT overwrite `min_gaps`, so a transient parse flake cannot reset the counter; the counter SHALL advance and the extension SHALL stop the loop on reaching the limit

#### Scenario: A grown, swapped, oscillating, or reworded gap set advances the stall counter
- **WHILE** a loop is active and the only failing check is `doneness` with a `not`/absent/unparseable verdict
- **WHEN** the doneness gap set is not a proper subset of `min_gaps` — it grows, keeps equal cardinality with swapped members, oscillates down-swing to a previously-seen set, or is reworded to the same normalized membership
- **THEN** the consecutive-stall counter SHALL advance (this is not progress), so an asymmetric oscillation such as {a,b}→{a}→{a,b}→{a} cannot reset the counter forever, and the extension SHALL stop the loop on reaching the limit

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

### Requirement: Loop hold blocks continuation

THE opsx-loop extension SHALL honor a `loop_hold` front-matter field in the armed
change's review.md as an orchestrator-settable landing channel: WHILE a loop is active,
WHEN an agent turn ends AND review.md front-matter carries `loop_hold: true`, the
extension SHALL NOT inject a continuation turn; it SHALL clear the active loop, preserve
the worktree, and notify the user with the `loop_hold_reason` value. Setting the hold
requires no privilege (it is the fail-safe direction); clearing SHALL happen ONLY via the
explicit named re-arm `/opsx-loop <change-name>` — a human-only slash command — at which
point the extension SHALL remove the hold fields, surface "hold was set: <reason> —
cleared by re-arm" in the arm notification, and record the clearance in review.md
Execution Notes. Goal/conversation kickoff SHALL NEVER clear any change's hold. An
absent or non-`true` `loop_hold` field SHALL leave behavior unchanged.

#### Scenario: Hold set mid-loop lands instead of re-injecting
- **WHILE** a loop is active on a change
- **WHEN** the agent turn ends with review.md front-matter carrying `loop_hold: true` and a non-empty `loop_hold_reason`
- **THEN** the extension SHALL NOT inject a continuation turn, SHALL clear the loop preserving the worktree, and SHALL notify the user quoting the reason

#### Scenario: Hold true with a missing reason still lands
- **WHEN** the agent turn ends with review.md front-matter carrying `loop_hold: true` but an empty or absent `loop_hold_reason`
- **THEN** the extension SHALL still treat the loop as held — it SHALL NOT inject a continuation turn and SHALL clear the loop preserving the worktree — and SHALL notify the user with a generic held-without-reason message, because holding is the fail-safe direction and requires no privilege

#### Scenario: Named re-arm clears the hold and surfaces the reason
- **WHILE** a change's review.md carries `loop_hold: true`
- **WHEN** the user issues `/opsx-loop <that-change>`
- **THEN** the extension SHALL clear the hold fields BEFORE the turn-0 gate evaluation and regardless of its outcome (a green short-circuit must not leave a stale hold behind), SHALL include the prior reason in the arm notification, SHALL append an Execution Notes clearance line, and SHALL then proceed with normal kickoff evaluation (arming a worker turn, or — per the turn-0 gate check — reporting the change ready to archive WITHOUT arming when its gate is already green)

#### Scenario: Goal kickoff never clears a hold
- **WHILE** any change's review.md carries `loop_hold: true`
- **WHEN** the user issues `/opsx-loop goal <text>`
- **THEN** the extension SHALL leave that hold untouched

#### Scenario: Missing hold field changes nothing
- **WHEN** review.md front-matter carries no `loop_hold` field
- **THEN** continuation behavior SHALL be identical to the pre-hold contract

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

### Requirement: Frozen Intent Baseline

WHEN an explore session for a change concludes, THE openspec-explore skill SHALL write the agreed intent, constraints, and invariants to an `intent.md` file in the change directory, and THE openspec-loop orchestration SHALL treat that file as an immutable baseline.

#### Scenario: Explore writes the baseline
- **WHEN** the user finishes an explore session and confirms the intent
- **THEN** `openspec/changes/<change>/intent.md` SHALL exist containing the agreed intent, initial constraints, and invariants

#### Scenario: Loop does not mutate intent
- **WHILE** the loop is advancing a change
- **IF** the orchestrator or a subagent would change the meaning recorded in intent.md
- **THEN** the orchestration SHALL halt and request explicit human authorization rather than editing intent.md autonomously

### Requirement: Single Orchestrator Loop

THE openspec-loop skill SHALL drive a change through its lifecycle within a single orchestrator agent that, each cycle, consults opsx gate to discover the next failing check and performs the next step toward making the gate pass.

#### Scenario: Orchestrator advances on a red gate
- **WHILE** opsx gate reports the gate is red
- **WHEN** the orchestrator begins a cycle
- **THEN** it SHALL read the gate's failed-check report and perform exactly the next step needed to address the highest-priority failed check

#### Scenario: Loop stops on a green gate
- **WHEN** opsx gate exits 0 for the change
- **THEN** the orchestration SHALL stop advancing and SHALL report the change as ready to archive

#### Scenario: Loop is bounded
- **WHILE** the gate remains red
- **IF** the orchestration reaches the iteration budget configured as `loop_max_iterations` in review.md front-matter
- **THEN** it SHALL stop and SHALL report the budget as exhausted with the remaining failed checks

### Requirement: Subagent Review Against Baseline

THE openspec-loop orchestration SHALL delegate every review and validation-judgment step to a blind subagent, and that subagent SHALL judge the current work against the phase-appropriate baseline rather than against the orchestrator's own reasoning.

#### Scenario: Review is delegated, not self-performed
- **WHEN** a review or validation-judgment step is required
- **THEN** the orchestration SHALL dispatch a subagent that has not seen the orchestrator's prior reasoning for that step, and SHALL use the subagent's written verdict

#### Scenario: Baseline widens by phase
- **WHEN** a pre-design review subagent is dispatched
- **THEN** its baseline SHALL be intent.md
- **WHEN** a post-apply review subagent is dispatched
- **THEN** its baseline SHALL be intent.md together with the proposal, specs, design, plan, and tasks status (matching the code-review baseline), so the reviewer can check the implementation followed the approved execution and verification path

#### Scenario: Doneness judge baseline is intent and diff
- **WHEN** the doneness judge subagent is dispatched
- **THEN** its baseline SHALL be the frozen intent.md together with the actual
  `Diff Base SHA..HEAD` diff and the change's delta acceptance criteria, and it SHALL rule
  `satisfied` only when the intent's stated outcomes are met without demanding beyond-scope
  work

### Requirement: Harness Neutral Core With Adapters

THE openspec-loop workflow logic SHALL reside in harness-neutral artifacts (the skill body, opsx gate, and the manifest), and subagent dispatch and loop continuation SHALL be resolved through capability hooks that degrade to inline execution when no harness adapter is available.

#### Scenario: Runs without a subagent adapter
- **IF** no subagent-dispatch capability is registered on the host
- **THEN** the orchestration SHALL perform the review step inline and mark it `review_mode: degraded-single-model`, which preserves structural enforcement but does NOT satisfy a gating-required code-review (the gate treats it as failed); the orchestration SHALL recommend running adversarial-review-cycle manually to reach a passing review

#### Scenario: Workflow substance survives adapter removal
- **WHEN** the host's loop-continuation adapter is unavailable
- **THEN** the workflow definition SHALL remain executable using the harness-neutral skill and opsx gate, driven by a fallback continuation mechanism

#### Scenario: Single budget governs the loop
- **WHEN** the kickoff adapter starts the loop on a host whose loop runtime already has a turn budget (such as the goal extension)
- **THEN** the adapter SHALL set that runtime's turn budget from `loop_max_iterations`, so exactly one budget governs the loop and the two cannot disagree

---

### Requirement: Doneness Judge Dispatch

THE openspec-loop orchestration SHALL produce a blind doneness verdict on the resolved `review` role model and seal it into `doneness.md` with provenance and a fresh reviewed range, WHILE a change requires a doneness verdict (Scale M or above and `doneness_mode` is `required`), doing so after the mechanical gate checks pass and before treating the gate as green, so intent-satisfaction is judged upstream and the gate only reads the sealed field. THE DISPATCH CHANNEL SHALL be tier-conditioned: WITH the `full_rigor` review.md front-matter flag set, the verdict SHALL be produced by an INDEPENDENTLY dispatched blind doneness judge (a separate blind subagent, the current top-tier behavior); at Scale M WITHOUT `full_rigor`, the doneness question SHALL instead ride the blind code-review dispatch — answered by the SAME blind reviewer as a dedicated, final required section of that dispatch — with the verdict STILL sealed to a SEPARATE `doneness.md` carrying the same adapter-stamped provenance and freshness fields, so the gate's doneness artifact requirement, the freshness/provenance binding, and the every-Scale>=M-requires-doneness policy are unchanged and only the extra independent dispatch is eliminated at plain M.

#### Scenario: Judge dispatched after mechanical checks pass
- **WHILE** the doneness verdict is required for the change
- **WHEN** the mechanical gate checks (structure, required artifacts, tasks, validation,
  verify, code-review) pass but no fresh satisfied doneness verdict exists
- **THEN** the orchestration SHALL produce the blind doneness verdict on the `review` role
  model — via the independently dispatched blind doneness judge WITH `full_rigor`, or via
  the dedicated final section of the blind code-review dispatch at plain Scale M — and
  write it to `doneness.md` before re-running opsx gate

#### Scenario: Full-rigor retains the independent judge dispatch
- **WHILE** the doneness verdict is required AND the change's review.md front-matter sets `full_rigor: true`
- **WHEN** the orchestration produces the doneness verdict
- **THEN** it SHALL dispatch an INDEPENDENT blind doneness judge (a subagent separate from the code-review reviewers) on the `review` role model and seal its verdict to `doneness.md`, retaining the current top-tier behavior

#### Scenario: Plain M rides the code-review dispatch
- **WHILE** the doneness verdict is required AND the change is Scale M WITHOUT `full_rigor`
- **WHEN** the orchestration produces the doneness verdict
- **THEN** the doneness question SHALL be answered by ONE designated blind reviewer as a dedicated final required section of the code-review dispatch (no separate doneness dispatch) — WHERE the dispatch resolves more than one `review`-role model, the designated reviewer SHALL be the FIRST model in the resolved `review` role set so exactly one verdict is sealed — and its verdict SHALL STILL be sealed to a separate `doneness.md` with adapter-stamped `blind-single-judge` provenance and a fresh reviewed range, so the gate reads the sealed field exactly as before and the 2-model blind code review is not weakened by co-locating the doneness section

#### Scenario: Orchestrator never self-authors the doneness verdict
- **WHEN** a doneness verdict is produced
- **THEN** it SHALL be authored by the blind reviewer/judge subagent (not the orchestrator), and its
  reviewer-provenance field SHALL be stamped by the subagent-dispatch adapter (not written
  in-band by the orchestrator), matching the adapter-stamped code-review delegation rule

#### Scenario: No dispatch adapter degrades to a failed check, never a silent pass
- **WHILE** the doneness verdict is required but no subagent-dispatch adapter is registered
- **WHEN** the orchestration attempts to produce the verdict
- **THEN** it SHALL either leave `doneness.md` absent or seal it with `Doneness: not` (it
  SHALL NOT seal a `satisfied` verdict stamped `degraded-single-model`), and record a notice
  that a green doneness verdict is reachable only via a dispatch-capable harness or an
  explicit `doneness_mode: waived` with a non-empty rationale; the gate SHALL treat the
  absent or `not` verdict as a failed check. Constraining the adapterless state to
  absent-or-`not` (never a degraded `satisfied`) maps it to the stall detector's bounded
  gap-set/empty-set signal, so an adapterless Scale >= M loop STALLS rather than spinning
  forever on a re-reproducible degraded `satisfied`. The harness-neutral guarantee is that
  ENFORCEMENT persists without the adapter (the deterministic gate still evaluates the
  check), NOT that a passing verdict is reachable adapterless

#### Scenario: Bare waiver at Scale M and above is resolved within the loop
- **WHILE** the change declares Scale M or above and `doneness_mode` is `waived` without a
  non-empty `doneness_waiver_rationale` (so the gate still fails `doneness`)
- **WHEN** the orchestration evaluates the turn
- **THEN** it SHALL either dispatch the doneness judge or surface the missing-rationale
  requirement to the worker, so the failing gate is resolvable within the loop rather than
  only by the stall backstop bailing out

#### Scenario: Judge re-dispatched on a stale verdict
- **WHILE** a prior doneness verdict exists but its reviewed range no longer matches the
  current HEAD
- **WHEN** the orchestration evaluates doneness
- **THEN** it SHALL re-dispatch the doneness judge against the current HEAD rather than reuse
  the stale verdict

### Requirement: Review Dispatch Bound By Convergence Discipline

THE openspec-loop orchestration SHALL conduct gating review rounds under the opsx-adversarial-review discipline: full-diff blind re-review each round, an orchestrator-maintained round ledger, the trajectory/budget stop conditions, at most one disclosure round on persistent split, and the decision-audit landing when open P0/P1 findings survive the stops.

#### Scenario: Re-dispatch consults the stop conditions first
- **WHEN** a gating review round returns a fail verdict and fixes have been committed
- **THEN** the orchestration SHALL evaluate the convergence stop conditions (converged, treadmill trajectory, round budget) before dispatching the next blind round, and SHALL NOT dispatch when a stop condition holds

#### Scenario: Non-convergence lands, never spins
- **IF** stop conditions fire with open P0/P1 findings (after any disclosure round)
- **THEN** the orchestration SHALL present the decision-audit landing to the user instead of continuing review cycles or escalating to additional reviewer models

#### Scenario: Landing halts loop continuation
- **WHEN** the decision-audit landing is presented
- **THEN** the orchestration SHALL stop the drive-to-green loop's continuation by setting `loop_hold: true` with a reason pointing at the audit (per the terminal-landing requirement); WHERE the loop host does not support `loop_hold`, performing no further change-directory or commit activity (so the host's stall detection stops the loop) remains the fallback — in both cases presenting the audit exactly once rather than re-presenting it on every re-injected turn

### Requirement: Pre Apply Surface Audit Dispatch

WHERE the frozen intent is property-style (a codebase-wide property claim rather than an enumerable diff), THE orchestration SHALL dispatch the advisory surface audit before the first implementation task, and SHALL feed its enumeration into tasks.md and the intent's stated-scope prose before gating reviews begin.

#### Scenario: Audit precedes implementation
- **WHEN** apply begins for a property-style intent without a completed surface audit
- **THEN** the orchestration SHALL dispatch the advisory audit before executing implementation tasks

#### Scenario: Enumerable-diff intents skip the audit
- **WHERE** the intent enumerates its scope concretely
- **THEN** no surface audit dispatch is required

### Requirement: Scope Widening Handled In The Loop

WHILE the loop is advancing a change, WHEN a gating reviewer or the doneness judge reports a finding outside the intent's stated scope, THE orchestration SHALL apply the opsx-adversarial-review scope-widening protocol (as specified by that capability) rather than silently fixing, silently dropping, or halting on every out-of-scope finding.

#### Scenario: Widening logged before fixing
- **WHEN** the orchestration decides an out-of-scope finding is required to meet the frozen intent
- **THEN** it SHALL record the Scope Expansions entry (what + evidence) in review.md before committing the fix

#### Scenario: Deferral is visible
- **WHEN** the orchestration routes an out-of-scope finding to follow-ups.md
- **THEN** the routing SHALL be recorded with the finding's severity and origin so the archive step can surface it

---

### Requirement: Terminal landings set the loop hold

THE orchestrator SHALL, WHEN declaring a landing state that must not be re-driven by
loop continuation — a decision-audit landing after review non-convergence, a terminal
green-gate report already presented, or any stop that awaits a human ruling — set
`loop_hold: true` with a non-empty `loop_hold_reason` in the change's review.md
front-matter — the same copy the loop host resolves from the integration checkout, so
the hold is observable to the host — committed as part of the landing turn, instead of
relying on prose
announcements or stall-guard exhaustion, so the host loop observes the landing
deterministically. The orchestrator SHALL NEVER clear a `loop_hold` itself — clearing is
reserved to the human named re-arm.

#### Scenario: Decision-audit landing holds the loop
- **WHEN** the orchestrator presents a decision audit after review stop conditions fire
- **THEN** it SHALL set `loop_hold: true` with a reason pointing at the audit before ending the turn, and the loop SHALL NOT re-inject a continuation

#### Scenario: Orchestrator never clears its own hold
- **WHILE** review.md carries `loop_hold: true`
- **WHEN** the orchestrator concludes further work is warranted
- **THEN** it SHALL surface that recommendation to the user and SHALL NOT remove the hold fields itself

#### Scenario: Hold is written to the copy the loop host reads
- **WHILE** the change's verdict artifacts (verify.md, code-review.md, doneness.md) live in the apply worktree
- **WHEN** the orchestrator sets a landing hold
- **THEN** it SHALL write and commit the `loop_hold` fields in the review.md resolved from the INTEGRATION checkout (the copy the loop host and gate read), not solely the worktree copy, so the hold cannot be split-brained into invisibility

### Requirement: TUI scenarios exercise user-visible slash commands

THE opsx-loop test suite SHALL exercise the user-facing `/opsx-loop` command paths in a real Pi TUI and SHALL assert pane-visible feedback for each command, so regressions where handlers return discarded strings instead of notifying are caught.

#### Scenario: Status and bare command are visible
- **WHEN** the scenario driver sends `/opsx-loop` and `/opsx-loop status` into a real Pi TUI with no active loop
- **THEN** the suite SHALL assert that the pane shows a no-active-loop notification

#### Scenario: Clear command is visible
- **WHEN** the scenario driver sends `/opsx-loop clear` into a real Pi TUI with no active loop
- **THEN** the suite SHALL assert that the pane shows a no-active-loop-to-clear notification

#### Scenario: Models subcommand preserves arguments
- **WHEN** the scenario driver sends `/opsx-loop models set author claude-bridge/claude-haiku-4-5` into a real Pi TUI
- **THEN** the suite SHALL assert that the fake `opsx models` command receives `set author claude-bridge/claude-haiku-4-5` intact and that its output is visible in the pane

### Requirement: TUI scenarios exercise deterministic loop states

THE opsx-loop test suite SHALL run deterministic TUI scenarios for green gates, red gates, status, clear, goal distillation, and loop hold/re-arm without requiring real hosted model calls in the default run.

#### Scenario: Already-green change does not arm
- **WHEN** the scenario driver sends `/opsx-loop <change>` for a temp change whose fake `opsx gate` exits zero
- **THEN** the suite SHALL assert that the pane reports the change ready to archive and that no worker turn is injected

#### Scenario: Red change arms and can be cleared
- **WHEN** the scenario driver sends `/opsx-loop <change>` for a temp change whose fake `opsx gate` exits non-zero
- **THEN** the suite SHALL assert that the pane reports an active loop, a worker directive is injected, `/opsx-loop status` names the active change, and `/opsx-loop clear` prevents further continuation

#### Scenario: Goal distill pauses for intent confirmation
- **WHEN** the scenario driver sends `/opsx-loop goal build a multi word thing` and the fake agent turn creates a new change with `intent.md`
- **THEN** the suite SHALL assert that the full goal text reaches the distill directive, the loop stops, and the pane names the new intent path awaiting confirmation

#### Scenario: Loop hold stops continuation and named re-arm clears it
- **WHILE** a temp change has `loop_hold: true` and a non-empty `loop_hold_reason` in `review.md`
- **WHEN** the scenario driver reaches an `agent_end` continuation point and then sends `/opsx-loop <change>` again
- **THEN** the suite SHALL assert that continuation stops with the hold reason, named re-arm clears the hold state, and the re-arm notification includes the previous reason

### Requirement: Scenario harness is isolated and signal-driven

THE opsx-loop TUI scenario harness SHALL isolate each scenario from the user's real Pi sessions and OpenSpec workspace, and SHALL wait on explicit signals rather than fixed sleeps for scenario completion.

#### Scenario: Private tmux server per scenario
- **WHEN** a scenario starts
- **THEN** the harness SHALL create a unique tmux server/socket for that scenario and tear it down after pass, fail, or timeout without using broad process kills

#### Scenario: Temp repo and fake commands isolate state
- **WHEN** a scenario runs
- **THEN** the harness SHALL use a temp repo and prepend fake `opsx`/fixture commands to `PATH`, recording argv, cwd, and relevant env for assertions without mutating the user's real OpenSpec changes

#### Scenario: Completion waits use observable signals
- **WHEN** a scenario waits for Pi, a command result, a fake provider turn, or a fake `opsx` invocation
- **THEN** the harness SHALL wait for pane regexes or fixture log counters before asserting outcomes, with only minimal draw-settle sleeps after a signal

#### Scenario: Real-model smoke is opt-in
- **IF** a real-provider smoke scenario is present
- **THEN** the default runner SHALL skip it unless an explicit environment flag enables it, and SHALL document required credentials and flake/cost trade-offs

---

