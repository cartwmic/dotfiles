<!-- authored: in-session -->
# Execution Plan

## Plan step 1: Arm/clear tool mute + opsx_dispatch registration

- **Covers:** T1.1, T3.1
- **Pre-conditions:**
  - Specs + tasks committed; apply worktree via `opsx worktree ensure`
  - Existing `dot_pi/agent/extensions/opsx-loop/` + `helpers.test.ts`
- **Action:**
  1. Write failing tests for arm → active tools exclude `subagent` and include
     `opsx_dispatch`; clear → snapshot restored (cite
     `opsx-loop.armed-loop-mutes-generic-subagent-tool`)
  2. Run `bun test dot_pi/agent/extensions/opsx-loop/` → expect FAIL
  3. Register `opsx_dispatch`; on arm snapshot + `setActiveTools`; on clear/stop
     restore snapshot
  4. Run tests → expect PASS
  5. Commit (`feat: opsx-loop mute subagent and expose opsx_dispatch`)
- **Verification:** `bun test dot_pi/agent/extensions/opsx-loop/`
- **Rollback:** revert extension tool-set helpers + tests

## Plan step 2: Role resolve, refuse, force model, review fan-out, library spawn

- **Covers:** T1.2, T1.3, T3.2
- **Pre-conditions:** Step 1 green (tool surface exists)
- **Action:**
  1. Write failing tests: refuse when !armed; refuse unset role with actionable
     hint; configured role forces model (caller `model` ignored); review list
     spawns N times; spawn stub receives forced model via library path (cite
     `opsx-loop.opsx-dispatch-forces-resolved-role-model`,
     `opsx-loop.review-role-auto-fan-out`,
     `opsx-loop.dispatch-spawns-via-subagent-library`)
  2. Run → expect FAIL
  3. Implement resolve + refuse + fan-out + `runSync` (or equivalent) import with
     injectable spawn for tests; no OPSX reads inside pi-subagents
  4. Run → expect PASS
  5. Commit (`feat: opsx_dispatch forces role models via runSync`)
- **Verification:** `bun test dot_pi/agent/extensions/opsx-loop/`
- **Rollback:** revert dispatch execute path + spawn stub tests

## Plan step 3: Skill prose — armed routes through opsx_dispatch

- **Covers:** T2.1
- **Pre-conditions:** Steps 1–2 green (tool name/behavior stable)
- **Action:**
  1. Update `openspec-loop` (+ propose/apply refs that dispatch role-bound
     subagents) to require `opsx_dispatch` while loop armed; document disarmed
     `subagent` path and unset-role refuse (cite
     `opsx-skill-integration.skills-honor-configured-role-models`)
  2. Grep skills for soft-honor-only `subagent`+`model:` under loop armed → none
  3. Commit (`docs: route armed-loop role dispatch via opsx_dispatch`)
- **Verification:** skill prose review; extension suite still green
- **Rollback:** revert skill markdown hunks

## Completion Verification

- `bun test dot_pi/agent/extensions/opsx-loop/` exits 0
- `opsx gate opsx-loop-role-dispatch --worktree <path>` progresses past
  validation `opsx-loop-extension-tests` once implementation lands
- Skills under `dot_local/share/agent-harness/canonical/skills/openspec-loop/`
  document armed `opsx_dispatch` vs disarmed `subagent`

## Manual Adjustments

- Plain-M: no standalone clarify/design/analyze; decisions frozen in intent +
  proposal Open Questions.
- Execution Mode standard (not tdd-required): plan uses ordered TDD-flavored
  steps as discipline, not a gate-enforced red/green cycle.
- Delegation Mode subagent-required: apply may dispatch plan steps via
  pi-subagents with `impl` model (`cursor/composer-2.5` pinned).
- Structure `openspec validate --strict` still red on ADDED SHALL parse for
  three opsx-loop requirements — fix as next gate unit before apply if it
  blocks progress (likely multi-line requirement body / leading WHILE).
