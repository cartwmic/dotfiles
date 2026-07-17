<!-- authored: in-session -->
# Proposal — opsx-dispatch-transparent

## Why

Armed-loop `opsx_dispatch` binds role models but obfuscates the subagent UX:
`onUpdate` dropped, one-liner results, no renderers, and review fan-out is a
custom sequential `runSync` loop. Operators lose live progress/metadata while
skills learn a divergent call surface. Fix transparency + native parallel
review fan-out in the opsx-loop shim (Constitution I/II; pi-subagents stays
OPSX-blind).

## What Changes

- **BREAKING (armed path only):** review multi-list + single `task` expands to
  native pi-subagents parallel `tasks[]` (not sequential spawns). Order and
  forced models preserved.
- `opsx_dispatch` schema: `role` + `task` XOR `tasks[]` (+ `agent`, optional
  `concurrency`). Caller `tasks[]` allowed; models forced; review length must
  match list or refuse.
- Forward `onUpdate`; return subagent-shaped `Details`; attach
  `renderCall`/`renderResult` reusing pi-subagents renderers.
- Skills: document native-parallel review fan-out on armed path (still one
  `opsx_dispatch` call).
- Hermetic tests for onUpdate, Details shape, parallel expansion, length
  mismatch refuse; prior mute/unset/sole-source suite stays green.

## Capabilities

### New Capabilities
- (none)

### Modified Capabilities
- `opsx-loop`: Transparent shim (onUpdate/Details/renderers); narrow schema;
  review fan-out → native parallel `tasks[]`; caller `tasks[]` passthrough with
  forced models.
- `opsx-skill-integration`: Armed-path skill prose describes native-parallel
  fan-out via one `opsx_dispatch` (not N sequential calls).

## Impact

**Affected files (expected):**
- `dot_pi/agent/extensions/opsx-loop/` (`helpers.ts`, `spawn.ts`, `index.ts`,
  tests)
- `dot_local/share/agent-harness/canonical/skills/openspec-{loop,propose,apply-change}/`
- Delta specs under `openspec/changes/opsx-dispatch-transparent/specs/`

**Dependencies:** pi-subagents library (`runSync` / executor parallel path /
render exports). One-way: opsx-loop → pi-subagents. Sibling
`opsx-loop-models-interactive` untouched.

## Open Questions (plain-M clarify-in-proposal)

### Q1: Wrapper shape?
- **A (chosen):** Keep `opsx_dispatch`, mute generic `subagent` while armed;
  forward executor/`runSync` with `onUpdate`.
- B: Same-name override of `subagent` while armed.
- **Resolution:** A — frozen intent; restore-friendly; one-way dep.

### Q2: Schema depth?
- **A (chosen):** `role` + `task` | `tasks[]` (+ `agent` / `concurrency`).
- B: Full SubagentParams passthrough.
- **Resolution:** A — explore freeze; chain/async/worktree deferred.

### Q3: Review fan-out mechanism?
- **A (chosen):** Expand single `task` + N review models → native parallel
  `tasks[]`.
- B: Keep sequential custom loop; only add onUpdate.
- **Resolution:** A — user-confirmed; supersedes role-dispatch sequential.

### Q4: Caller `tasks[]` vs review list length?
- **A (chosen):** Length must equal resolved review list; else refuse.
- B: Pad/truncate silently.
- **Resolution:** A — fail-closed; actionable error.

### Q5: Renderer reuse?
- **A (chosen):** Import/wrap `renderSubagentResult` (and call renderer) from
  pi-subagents.
- B: Hand-roll thin local renderer.
- **Resolution:** A — fidelity to subagent UX; still OPSX-blind library use.

### Q6: Full SubagentParams / slash mute?
- **A (chosen for v1):** Defer (intent non-goals).
- B: Include in this change.
- **Resolution:** A.

## Deterministic analyze (plain-M, inline)

| Check | Result |
|---|---|
| 1 Tiling | Modified `opsx-loop` + `opsx-skill-integration` cover transparency, schema, parallel fan-out, skill docs |
| 2 Traceability | Intent constraints map to MODIFIED/ADDED ACs in those deltas |
| 7 EARS lint | WHILE armed / WHEN dispatch; IF length mismatch THEN refuse |

No blockers. Outstanding risk: pi-subagents parallel entry may need
`createSubagentExecutor` deps (ExtensionContext) — prefer composing
`runSync`+`onUpdate` into parallel Details if executor wiring is too heavy;
record choice in Execution Notes if so.

## Assumptions recorded

- Scale M, `full_rigor: false` per frozen intent; design.md skipped
  (decision-gated — explore froze wrapper/schema/parallel/renderer).
- Standalone clarify.md / analyze.md skipped (plain-M).
- Bind/mute/unset-refuse/OPSX-blind constraints from archived
  `opsx-loop-role-dispatch` remain; this change supersedes sequential fan-out
  only.
- Sibling `opsx-loop-models-interactive` remains separate.
