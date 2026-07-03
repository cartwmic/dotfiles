<!-- authored: in-session -->
# Capability: opsx-loop-kickoff

## MODIFIED Requirements

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

## ADDED Requirements

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

#### Scenario: Named re-arm clears the hold and surfaces the reason
- **WHILE** a change's review.md carries `loop_hold: true`
- **WHEN** the user issues `/opsx-loop <that-change>`
- **THEN** the extension SHALL clear the hold fields, SHALL include the prior reason in the arm notification, SHALL append an Execution Notes clearance line, and SHALL arm the loop normally

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
absent, empty, or fails validation, using the fallback iff the probed path is a valid git
worktree for the change's branch (`opsx/<change>`); WHEN both the locator and the
convention path fail, resolution SHALL yield no worktree (current behavior), never a
guess.

#### Scenario: Empty locator resolves via convention path
- **WHILE** review.md in the integration checkout carries no usable `Worktree Path`
- **IF** the canonical `opsx worktree` path for the change exists and is a valid git worktree on branch `opsx/<change>`
- **THEN** the extension SHALL resolve that path and pass it as the gate's `--worktree`

#### Scenario: No locator and no convention worktree degrades safely
- **WHILE** the locator is empty AND the convention path is absent or invalid
- **THEN** resolution SHALL yield no worktree and the gate SHALL run without `--worktree`, unchanged from current behavior
