<!-- authored: in-session -->

## Why

The 2026-07-03 loop session exposed four gaps that let the opsx-loop extension
re-prompt through terminal states and mis-resolve worktrees: goal-mode kickoff
has no defined relationship to pre-existing changes (an agent latch is
extension-invisible), the distill directive's generic autonomy blurb
contradicts its own STOP instruction, agents have no invokable loop-stop
channel for decision-audit landings, and the worktree locator lives only on
the change branch while the gate resolves it from the integration checkout.
One of these directly caused an archive to execute on a machine re-prompt
misread as human authorization.

## What Changes

- **Latch contract (G-A):** `goal`/conversation kickoff NEVER latches a
  pre-existing change; explicit `/opsx-loop <change-name>` is the sole latch
  spelling; NO goal-text↔change-name matching (false-latch footgun). Distill
  kickoff directive gains a deterministic active-change inventory (dir listing
  + front-matter parse; no gate runs, no model) instructing the agent to stop
  and point the user at resume when an existing change covers the goal.
- **Distill-scoped autonomy (G-B):** distill directive's autonomy text becomes
  distill-specific (draft, do NOT implement, STOP after announcing); the
  drive-to-green blurb stays on worker/continuation directives only.
- **`loop_hold` landing channel (G-C):** review.md front-matter `loop_hold` +
  mandatory `loop_hold_reason`; extension checks at agent_end before
  re-injecting and disarms with the reason; cleared ONLY by explicit named
  re-arm (human-only slash command), surfaced at arm time; goal kickoff never
  clears. openspec-loop skill landing prose updates to set it.
- **Locator convergence (G-D):** apply skill commits `Worktree Path` +
  `Diff Base SHA` to the integration checkout at worktree creation (primary);
  `opsx gate` + extension `resolveWorktree` gain a convention-path fallback
  probing the canonical `opsx worktree` path when the locator is empty/stale.
- **Stall-guard off-by-one (in-scope fix):** seed `lastDirs` at arm time from
  the already-captured `preChangeDirs` so STALL_LIMIT=3 costs 3 distill turns
  (currently 4: turn-1 evaluation only initializes the baseline), keeping the
  stall notify's "after 3 turns" wording truthful.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `opsx-loop-kickoff`: latch contract, inventory in distill kickoff,
  distill-scoped autonomy, `loop_hold` check/clear semantics, stall-guard
  seeding, locator fallback in `resolveWorktree`.
- `opsx-loop-orchestration`: decision-audit/terminal landing prescribes
  setting `loop_hold` (replaces "halt via host loop-stop, else stall
  detection").
- `opsx-gate-enforcement`: gate worktree resolution gains the convention-path
  fallback; locator-field publication requirement (integration checkout).
- `opsx-workflow-schema`: review.md template documents `loop_hold` +
  `loop_hold_reason` front-matter keys.
- `opsx-cli`: read-only `opsx worktree path <change>` subcommand — single source
  for the convention path consumed by the gate and extension fallbacks.

## Impact

- **Extension:** `dot_pi/agent/extensions/opsx-loop/index.ts` (distill
  directive + inventory, loop_hold check at agent_end, clear-on-named-re-arm,
  stall-guard seeding, resolveWorktree fallback), `helpers.ts` if parsing
  moves there, `helpers.test.ts` + extension test file for new behavior.
- **Gate CLI:** `dot_local/bin/executable_opsx` (worktree resolution
  fallback; loop_hold is orchestrator-read, NOT a gate check — gate stays
  ignorant of it).
- **Skills (Constitution IX — existing-skill edits):**
  `dot_local/share/agent-harness/canonical/skills/openspec-loop/SKILL.md`
  (landing prose → set loop_hold),
  `dot_local/share/agent-harness/canonical/skills/openspec-apply-change/references/opsx-superpowers-mode.md`
  (locator publication to integration checkout at worktree creation).
- **Templates:** `dot_local/share/openspec/schemas/opsx-superpowers/templates/review.md`
  (loop_hold key documentation).
- **Tests:** extension test suite (loop_hold, inventory, stall seeding,
  fallback), `tests/opsx-gate` (locator fallback), surface assertions where
  prose promises are load-bearing.
- **Non-breaking:** absent `loop_hold` ⇒ current behavior; empty locator +
  no convention worktree ⇒ current behavior (no `--worktree`).
