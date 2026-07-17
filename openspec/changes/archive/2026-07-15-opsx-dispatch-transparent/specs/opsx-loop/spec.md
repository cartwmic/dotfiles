<!-- authored: in-session -->
# Capability: opsx-loop

## ADDED Requirements

### Requirement: Opsx Dispatch Narrow Schema

THE opsx-loop extension SHALL expose `opsx_dispatch` with a narrow schema of
`role` plus either a single `task` or a parallel `tasks[]` array, and MAY
accept `agent` and optional `concurrency` companions for those modes. THE
extension SHALL NOT require chain, async, worktree, or management `action`
parameters for v1 of this surface.

#### Scenario: Single task accepted
- **WHILE** a loop is armed and a role is configured
- **WHEN** `opsx_dispatch` is invoked with `role` and `task` (no `tasks`)
- **THEN** THE extension SHALL accept the call (subject to role resolve rules)

#### Scenario: Parallel tasks array accepted
- **WHILE** a loop is armed and a role is configured
- **WHEN** `opsx_dispatch` is invoked with `role` and `tasks` (non-empty)
- **THEN** THE extension SHALL accept the call as a parallel dispatch shape

#### Scenario: Both task and tasks refused
- **WHILE** a loop is armed
- **IF** `opsx_dispatch` is invoked with both `task` and `tasks` set
- **THEN** THE extension SHALL refuse with an actionable error

### Requirement: Opsx Dispatch Transparent Progress And Details

WHEN `opsx_dispatch` performs a spawn, THE opsx-loop extension SHALL forward
the tool `onUpdate` callback into the pi-subagents programmatic spawn path,
return a subagent-shaped `Details` payload (including progress and results
metadata rather than a one-liner-only summary), and attach `renderCall` /
`renderResult` that reuse pi-subagents renderers (import or thin wrap).

#### Scenario: onUpdate forwarded during spawn
- **WHILE** a loop is armed and a configured role is dispatched
- **WHEN** the underlying spawn emits progress updates
- **THEN** THE extension SHALL invoke the parent tool `onUpdate` with
  subagent-shaped progress/details rather than suppressing them

#### Scenario: Result carries Details not one-liner-only
- **WHEN** `opsx_dispatch` completes a successful spawn
- **THEN** THE tool result SHALL include subagent-shaped `Details` (mode,
  results, and progress metadata) and SHALL NOT regress to a sole
  `spawn complete model=… exit=…` text body with empty details

#### Scenario: Renderers reuse subagent visuals
- **WHEN** the `opsx_dispatch` tool is registered
- **THEN** it SHALL provide `renderCall` and `renderResult` that reuse
  pi-subagents renderer exports (or a thin wrap of them)

### Requirement: Caller Tasks Length Must Match Review List

THE opsx-loop extension SHALL, WHILE a loop is armed and `role: "review"`
resolves to a multi-value list and WHEN the caller passes `tasks[]`, require
`tasks.length` to equal the resolved review list length, force each entry's
model from the list by index (ignoring caller per-task `model`), and IF the
lengths differ THEN refuse with an actionable error. For single-model roles,
WHEN the caller passes `tasks[]`, THE extension SHALL stamp every entry with
that role's resolved model id.

#### Scenario: Review tasks length mismatch refuses
- **WHILE** review resolves to N model ids (N > 1)
- **IF** `opsx_dispatch` is invoked with `role: "review"` and `tasks` whose
  length is not N
- **THEN** THE extension SHALL refuse and SHALL NOT spawn

#### Scenario: Review tasks length match forces models by index
- **WHILE** review resolves to N model ids in order
- **WHEN** `opsx_dispatch` is invoked with `role: "review"` and `tasks` of
  length N
- **THEN** THE extension SHALL spawn in parallel with entry i forced to
  review model i, ignoring any caller-supplied per-task `model`

#### Scenario: Single-model role stamps all tasks entries
- **WHILE** `impl` resolves to one configured model id
- **WHEN** `opsx_dispatch` is invoked with `role: "impl"` and `tasks` of
  length K ≥ 1
- **THEN** every spawned entry SHALL use that impl model id

## MODIFIED Requirements

### Requirement: Review Role Auto Fan-Out

THE opsx-loop extension SHALL, WHILE a loop is armed and the `review` role
resolves to a multi-value list and WHEN `opsx_dispatch` is invoked with
`role: "review"` and a single `task` (no caller `tasks`), expand the dispatch
into a native pi-subagents parallel `tasks[]` spawn — one entry per list
model in list order, same task body, each entry's model forced — and SHALL
NOT perform a sequential custom `runSync` loop for that fan-out. WHEN review
resolves to exactly one model id and a single `task` is supplied, THE
extension SHALL spawn exactly one subagent with that model id.

#### Scenario: Multi-review list expands to native parallel tasks
- **WHILE** the resolved review list contains two or more model ids
- **WHEN** `opsx_dispatch` is invoked with `role: "review"` and a single
  `task`
- **THEN** THE extension SHALL expand to a native parallel `tasks[]` spawn
  with exactly one entry per list model, preserving order, each forced to
  that entry's model id, and SHALL NOT run those entries as a sequential
  custom loop

#### Scenario: Single review entry spawns once
- **WHILE** review resolves to exactly one model id
- **WHEN** `opsx_dispatch` is invoked with `role: "review"` and a single
  `task`
- **THEN** THE extension SHALL spawn exactly one subagent with that model id
