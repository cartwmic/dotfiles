<!-- authored: in-session -->
# Execution Plan

## Plan step 1: Schema + transparent spawn (onUpdate / Details / renderers)

- **Covers:** T1.1, T1.2, T4.1
- **Pre-conditions:**
  - Specs + tasks committed; apply worktree via `opsx worktree ensure`
  - Existing `opsx_dispatch` mute/bind from archived role-dispatch
- **Action:**
  1. Write failing tests for schema XOR, onUpdate forward, Details shape,
     renderer presence (cite narrow-schema + transparent-progress ACs)
  2. Run `bun test dot_pi/agent/extensions/opsx-loop/` → expect FAIL
  3. Implement schema + spawn path forwarding `onUpdate` + Details +
     renderer wrap (prefer `runSync`+`onUpdate`; escalate to executor
     parallel entry only if needed for Details fidelity)
  4. Run tests → expect PASS
  5. Commit (`feat: opsx_dispatch forwards onUpdate and Details`)
- **Verification:** `bun test dot_pi/agent/extensions/opsx-loop/`
- **Rollback:** revert spawn/index/helpers + tests

## Plan step 2: Native parallel review fan-out + caller tasks[]

- **Covers:** T2.1, T2.2, T4.2
- **Pre-conditions:** Step 1 green (transparent single-spawn works)
- **Action:**
  1. Write failing tests: multi-review + single task → parallel plan
     (count/order/models); length mismatch refuse; stamp-all for impl
     (cite review-role-auto-fan-out + caller-tasks-length ACs)
  2. Run → expect FAIL
  3. Replace sequential fan-out with native parallel `tasks[]` expansion;
     enforce length match; keep injectable spawn stub for hermetic tests
  4. Run → expect PASS (including prior mute/unset/sole-source suite)
  5. Commit (`feat: opsx_dispatch parallel review fan-out via tasks[]`)
- **Verification:** `bun test dot_pi/agent/extensions/opsx-loop/`
- **Rollback:** revert planner/spawn parallel path + tests

## Plan step 3: Skill prose — native-parallel armed review

- **Covers:** T3.1
- **Pre-conditions:** Steps 1–2 green (behavior stable)
- **Action:**
  1. Update openspec-loop (+ propose/apply refs) to document one
     `opsx_dispatch` owning native-parallel multi-review; forbid N
     sequential armed calls (cite skills-honor AC)
  2. Grep for sequential fan-out guidance under armed path → none
  3. Commit (`docs: opsx_dispatch native-parallel review fan-out`)
- **Verification:** skill prose review; extension suite still green
- **Rollback:** revert skill markdown hunks

## Completion Verification

- `bun test dot_pi/agent/extensions/opsx-loop/` exits 0
- `opsx gate opsx-dispatch-transparent --worktree <path>` progresses past
  validation once impl lands
- Armed skill prose: one call, tool-owned parallel fan-out

## Manual Adjustments

- Plain-M: no standalone clarify/design/analyze.
- Execution Mode standard; Delegation Mode subagent-required for gating
  code review (Constitution IX).
- Assumption: if `createSubagentExecutor` wiring proves too heavy for
  parallel Details, compose `runSync`+`onUpdate` into parallel Details
  shape — still library composition, OPSX-blind.
