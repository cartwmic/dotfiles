<!-- authored: in-session -->
# Execution Plan

## Plan step 1: Armed mute drops edit/write; expose bookkeep

- **Covers:** T1.1, T1.2, T5.1
- **Pre-conditions:**
  - Specs/design/tasks/plan committed; worktree via `opsx worktree ensure opsx-loop-pure-router`
  - Existing role-dispatch mute (`subagent` only) + transparent `opsx_dispatch` on main
- **Action (5-step micro-tasks):**
  1. Write failing tests: armed set excludes `edit`/`write`/`subagent`, includes
     `opsx_dispatch`+`opsx_bookkeep`; clear restores snapshot; bash retained
     (cite `opsx-loop.armed-loop-mutes-generic-subagent-tool`)
  2. Run `bun test dot_pi/agent/extensions/opsx-loop/` → expect FAIL on new cases
  3. Extend `applyArmedToolSet` / `restoreToolSetAfterClear`; constants
     `EDIT_TOOL_NAME`/`WRITE_TOOL_NAME`/`OPSX_BOOKKEEP_TOOL_NAME`; wire
     `ensureOpsxBookkeepTool` stub register in `index.ts` arm path
  4. Run tests → expect PASS (incl. prior mute suite)
  5. Commit (`feat: armed loop mutes edit/write and exposes opsx_bookkeep`)
- **Verification:** `bun test dot_pi/agent/extensions/opsx-loop/`
- **Rollback:** revert helpers/index/tests for mute+bookkeep register

## Plan step 2: opsx_bookkeep helpers + enum ops + tool register

- **Covers:** T2.1, T2.2, T2.3, T5.2
- **Pre-conditions:** Step 1 green (tool name present in armed set)
- **Action (5-step micro-tasks):**
  1. Write failing tests for refuse matrix + allow ops
     (`append_ledger`/`set_hold`/`append_followup`/`append_execution_note`;
     empty reason; `clear_hold` refuse; wrong change; not-armed)
     (cite `opsx-loop.opsx-bookkeep-structured-meta-tool`)
  2. Run → expect FAIL
  3. Implement pure helpers (+ optional `bookkeep.ts`) and register full
     `opsx_bookkeep` execute/render; INTEGRATION path only; sibling allowlist `[]`
  4. Run → expect PASS
  5. Commit (`feat: opsx_bookkeep structured meta writes on integration`)
- **Verification:** `bun test dot_pi/agent/extensions/opsx-loop/`
- **Rollback:** revert bookkeep module + register + tests

## Plan step 3: Armed author override in planOpsxDispatch

- **Covers:** T3.1, T5.3
- **Pre-conditions:** Steps 1–2 green
- **Action (5-step micro-tasks):**
  1. Write failing tests: armed + author configured + `authorInSession`
     true/unset → accept; armed + author unset → refuse no session fallback
     (cite `opsx-loop.armed-loop-forces-author-role-dispatch`)
  2. Run → expect FAIL
  3. Skip `authorInSession` refuse when `armed && role === "author"`; keep
     unset refuse; disarmed unchanged
  4. Run → expect PASS (prior sole-source/unset/transparent suite green)
  5. Commit (`feat: armed opsx_dispatch author ignores author_in_session`)
- **Verification:** `bun test dot_pi/agent/extensions/opsx-loop/`
- **Rollback:** revert `planOpsxDispatch` + author tests

## Plan step 4: Skill MUST-dispatch + bookkeep routing

- **Covers:** T4.1
- **Pre-conditions:** Steps 1–3 green (behavior stable)
- **Action:**
  1. Rewrite `openspec-{loop,propose,apply-change}` armed sections:
     author/impl/review → `opsx_dispatch`; meta → `opsx_bookkeep`; drop
     in-session author / "implement the next task" while armed; note bash
     residual; disarmed `author_in_session` unchanged
     (cite `opsx-skill-integration.skills-honor-configured-role-models`,
     `opsx-skill-integration.worktree-always-skill-discipline`)
  2. Grep armed skill prose for parent edit/write instruct on judged/meta → none
  3. Commit (`docs: armed loop pure-router MUST-dispatch and bookkeep`)
- **Verification:** skill prose review; extension suite still green
- **Rollback:** revert skill markdown hunks

## Completion Verification

- `bun test dot_pi/agent/extensions/opsx-loop/` exits 0
- All tasks.md checkboxes checked
- `opsx gate opsx-loop-pure-router --worktree <path>` progresses past
  validation once impl + reviews land
- Armed skill prose: no judged parent edit/write; bookkeep for meta

## Manual Adjustments

- Scale M, `full_rigor: true`; Execution Mode standard (5-step TDD used for
  extension steps; skill step is docs-only).
- Delegation Mode subagent-required (Constitution IX skill edits).
- Assumption: ledger/Execution-Notes append format copied from current
  openspec-loop skill examples during step 2; record any deviation in
  review.md Execution Notes.
- Sibling meta allowlist empty at v1 (design).
