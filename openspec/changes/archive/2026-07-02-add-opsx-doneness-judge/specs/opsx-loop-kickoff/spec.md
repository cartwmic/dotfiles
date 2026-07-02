<!-- authored: in-session -->
# opsx-loop-kickoff (delta)

## MODIFIED Requirements

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
