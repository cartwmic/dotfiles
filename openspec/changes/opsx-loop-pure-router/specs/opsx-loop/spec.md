<!-- authored: in-session -->
# Capability: opsx-loop

## ADDED Requirements

### Requirement: Opsx Bookkeep Structured Meta Tool

THE opsx-loop extension SHALL, WHILE an `/opsx-loop` session is armed for a
change, expose an `opsx_bookkeep` tool that mutates ONLY the armed change's
INTEGRATION copies of `openspec/changes/<change>/review.md` and
`openspec/changes/<change>/follow-ups.md` (and any sibling meta paths the
design explicitly allowlists). THE tool SHALL accept a structured operation
enum (not a free filesystem path). IF the operation is unknown, targets a
different change, targets a worktree-only path, or requests agent-initiated
hold clear, THEN THE extension SHALL refuse. Human named `/opsx-loop` re-arm
remains the sole hold-clear path.

#### Scenario: Append ledger row on integration review.md
- **WHILE** a loop is armed for change `C`
- **WHEN** `opsx_bookkeep` is invoked with an allowed append-ledger operation
  for `C`
- **THEN** THE extension SHALL mutate only the INTEGRATION
  `openspec/changes/C/review.md` (or the design-named ledger host) and SHALL
  NOT mutate product, spec, or task files

#### Scenario: Set loop hold via bookkeep
- **WHILE** a loop is armed for change `C`
- **WHEN** `opsx_bookkeep` is invoked with an allowed set-hold operation and a
  non-empty reason
- **THEN** THE extension SHALL set `loop_hold: true` and `loop_hold_reason` on
  INTEGRATION `openspec/changes/C/review.md`

#### Scenario: Agent hold clear refused
- **WHILE** a loop is armed
- **IF** `opsx_bookkeep` is invoked with a clear-hold operation
- **THEN** THE extension SHALL refuse and SHALL leave the hold unchanged

#### Scenario: Wrong change refused
- **WHILE** a loop is armed for change `C`
- **IF** `opsx_bookkeep` is invoked naming a different change `D`
- **THEN** THE extension SHALL refuse and SHALL NOT write any file

#### Scenario: Bookkeep refused when loop is not armed
- **WHILE** no loop is armed
- **IF** `opsx_bookkeep` is invoked
- **THEN** THE extension SHALL refuse (armed-loop-only surface)

### Requirement: Armed Loop Forces Author Role Dispatch

THE opsx-loop extension SHALL, WHILE a loop is armed and WHEN
`opsx_dispatch` is invoked with `role: "author"`, ignore the
`author_in_session` / `author-in-session` flag for gating that call: IF an
author role model is configured, THEN THE extension SHALL accept the dispatch
and force the resolved author model; IF the author role is unset, THEN THE
extension SHALL refuse with the existing unset/no-session-fallback semantics
and SHALL NOT silently author in the parent. WHEN the loop is cleared or no
loop is armed, THE prior `author_in_session` meaning for manual/disarmed
propose SHALL remain unchanged.

#### Scenario: Armed author dispatch allowed regardless of author_in_session
- **WHILE** a loop is armed, an author model is configured, and
  `author_in_session` is true or unset
- **WHEN** `opsx_dispatch` is invoked with `role: "author"` and a valid task
- **THEN** THE extension SHALL accept the dispatch and force the resolved
  author model (SHALL NOT refuse for author-in-session)

#### Scenario: Armed unset author still refuses
- **WHILE** a loop is armed and the author role is unset at every resolver
  layer
- **IF** `opsx_dispatch` is invoked with `role: "author"`
- **THEN** THE extension SHALL refuse with an actionable unset error and SHALL
  NOT fall back to the session model

#### Scenario: Disarmed author_in_session meaning preserved
- **WHILE** no loop is armed and `author_in_session` is true or unset
- **THEN** delegated author via `opsx_dispatch` SHALL remain unavailable
  (armed-only surface) and manual propose MAY continue in-session as before

## MODIFIED Requirements

### Requirement: Armed Loop Mutes Generic Subagent Tool

THE opsx-loop extension SHALL, WHILE an `/opsx-loop` session is armed for a
change, remove the generic `subagent` tool and the parent `edit` and `write`
tools from the active tool set, and SHALL expose `opsx_dispatch` and
`opsx_bookkeep` for role-bound judged work and structured meta writes.
Exact host tool name strings for edit/write SHALL match the names pi exposes
in the pre-arm active tool snapshot. WHEN the loop is cleared or stopped, THE
extension SHALL restore the prior active tool set so `subagent`, `edit`, and
`write` are available again per the snapshot, and `opsx_dispatch` /
`opsx_bookkeep` are not required outside an armed loop. Bash and read tools
MAY remain active while armed; muting edit/write does not by itself prevent
bash from rewriting files (accepted residual for this change).

#### Scenario: Arm drops subagent edit write and exposes dispatch tools
- **WHEN** the user starts `/opsx-loop <change>` and the loop arms
- **THEN** the active tool set SHALL exclude `subagent`, `edit`, and `write`,
  and SHALL include `opsx_dispatch` and `opsx_bookkeep`

#### Scenario: Clear restores prior tool set
- **WHILE** a loop is armed with `subagent`, `edit`, and `write` muted
- **WHEN** the user issues `/opsx-loop clear` (or an accepted stop alias)
- **THEN** the active tool set SHALL be restored to the pre-arm snapshot
  (including `subagent` / `edit` / `write` if they were active before arm)

#### Scenario: Disarmed sessions keep generic subagent
- **WHILE** no loop is armed
- **THEN** `opsx_dispatch` and `opsx_bookkeep` SHALL NOT be required for
  subagent or edit work and the generic `subagent` tool MAY remain active as
  before this change

#### Scenario: Bash retained while armed
- **WHILE** a loop is armed and `bash` was present in the pre-arm snapshot
- **THEN** the active tool set SHALL still include `bash` (gate/status
  commands remain available; shell mutate residual is accepted)

---

## Acceptance criterion quality checklist

| AC ID | Testable | Solution-free | Unambiguous | Consistent | Complete |
|---|---|---|---|---|---|
| opsx-loop.opsx-bookkeep-structured-meta-tool | [x] | [x] | [x] | [x] | [x] |
| opsx-loop.armed-loop-forces-author-role-dispatch | [x] | [x] | [x] | [x] | [x] |
| opsx-loop.armed-loop-mutes-generic-subagent-tool | [x] | [x] | [x] | [x] | [x] |
