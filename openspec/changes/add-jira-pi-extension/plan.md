<!-- authored: in-session -->
# Execution Plan — add-jira-pi-extension

Execution Mode = standard (not tdd-required). Steps are ordered lists mapping to tasks.

## Plan step 1: Deploy + domain

- **Covers:** T1.1, T1.2
- **Pre-conditions:** fidelity delivered; judged inputs committed
- **Action:**
  1. Add `.chezmoiignore` profile gate for `.pi/agent/extensions/jira/**`
  2. Amend `openspec/domain.md` Out-of-scope carve-out
  3. Commit
- **Verification:** `rg axon-work-computer .chezmoiignore`; domain carve-out present
- **Rollback:** revert those two files

## Plan step 2: Scaffold + MCP client

- **Covers:** T2.1, T2.2
- **Pre-conditions:** step 1 done
- **Action:**
  1. Create extension dir mirroring ntfy/hindsight layout
  2. Implement client (lazy connect, keep-alive, close on shutdown, sanitize errors)
  3. Smoke unit: mock connect/callTool shapes
  4. Commit
- **Verification:** `bun test` partial / client unit green offline
- **Rollback:** delete extension dir

## Plan step 3: Commands + bind

- **Covers:** T3.1, T3.2, T3.3
- **Pre-conditions:** client present
- **Action:**
  1. Bind state + guards
  2. Toggle/status/search/create
  3. Sync/transition/context latch
  4. Commit
- **Verification:** unit tests for command parsing + unbound refuse
- **Rollback:** revert command modules

## Plan step 4: Nudge

- **Covers:** T4.1
- **Pre-conditions:** toggle state exists
- **Action:**
  1. Wire `agent_end` counter + notify
  2. Tests for enabled/disabled cadence
  3. Commit
- **Verification:** nudge tests green
- **Rollback:** remove hook registration

## Plan step 5: Tests + gate + docs

- **Covers:** T5.1, T5.2, T5.3
- **Pre-conditions:** commands + nudge present
- **Action:**
  1. Complete mock MCP suite covering ACs
  2. Wire `openspec/opsx-gates.yaml` `jira-extension-tests`
  3. README
  4. Commit
- **Verification:** `bun test dot_pi/agent/extensions/jira/`; `opsx gate` validation slice includes new id
- **Rollback:** remove gate entry + tests

## Completion Verification

- `bun test dot_pi/agent/extensions/jira/` exits 0 offline
- `opsx gate add-jira-pi-extension --worktree <path>` reaches review/doneness (not missing tasks/fidelity)
- No opsx-loop / opsx schema files modified

## Manual Adjustments

- Standard execution (not tdd-required): plan uses ordered lists, not 5-step TDD micro-tasks.
- Assumption: extension auto-loads from `~/.pi/agent/extensions/` like siblings (recorded in proposal).
