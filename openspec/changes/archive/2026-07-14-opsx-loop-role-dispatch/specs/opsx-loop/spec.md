<!-- authored: in-session -->
# Capability: opsx-loop

## ADDED Requirements

### Requirement: Armed Loop Mutes Generic Subagent Tool

THE opsx-loop extension SHALL, WHILE an `/opsx-loop` session is armed for a
change, remove the generic `subagent` tool from the active tool set and
expose an `opsx_dispatch` tool for role-bound dispatch. WHEN the loop is
cleared or stopped, THE extension SHALL restore the prior active tool set so
`subagent` is available again and `opsx_dispatch` is not required outside an
armed loop.

#### Scenario: Arm drops subagent and exposes opsx_dispatch
- **WHEN** the user starts `/opsx-loop <change>` and the loop arms
- **THEN** the active tool set SHALL exclude `subagent` and SHALL include
  `opsx_dispatch`

#### Scenario: Clear restores prior tool set
- **WHILE** a loop is armed with `subagent` muted
- **WHEN** the user issues `/opsx-loop clear` (or an accepted stop alias)
- **THEN** the active tool set SHALL be restored to the pre-arm snapshot
  (including `subagent` if it was active before arm)

#### Scenario: Disarmed sessions keep generic subagent
- **WHILE** no loop is armed
- **THEN** `opsx_dispatch` SHALL NOT be required for subagent work and the
  generic `subagent` tool MAY remain active as before this change

### Requirement: Opsx Dispatch Forces Resolved Role Model

THE opsx-loop extension SHALL, WHILE a loop is armed and WHEN a worker
invokes `opsx_dispatch` with a role of `review`, `impl`, or (when authoring
is delegated) `author`, resolve that role via the same `opsx models` /
exported `OPSX_*` contract already used on loop start, force the resolved
model id into the subagent spawn path, and ignore any caller-supplied model
id for that spawn. THE role value SHALL be the sole source of the model id
for the spawn.

#### Scenario: Configured impl role forces model
- **WHILE** the loop is armed and `impl` resolves to a configured model id
- **WHEN** `opsx_dispatch` is invoked with `role: "impl"` and a task
- **THEN** the spawned subagent SHALL run with that resolved model id even
  if the caller also supplied a different `model` argument

#### Scenario: Caller model is ignored when role is configured
- **WHILE** the loop is armed and `review` resolves to configured model ids
- **WHEN** `opsx_dispatch` is invoked with `role: "review"` and a caller
  `model` that differs from the resolved set
- **THEN** THE extension SHALL NOT use the caller `model` for any spawn in
  that dispatch

#### Scenario: Unset role refuses dispatch
- **WHILE** the loop is armed and the requested role is unset at every
  resolver layer (no configured value)
- **IF** `opsx_dispatch` is invoked for that role
- **THEN** THE extension SHALL refuse the dispatch with an actionable error
  that points the operator at `opsx models set` / config layers, and SHALL
  NOT fall back to the session model on this path

#### Scenario: Dispatch refused when loop is not armed
- **WHILE** no loop is armed
- **IF** `opsx_dispatch` is invoked
- **THEN** THE extension SHALL refuse the call (armed-loop-only surface)

#### Scenario: Loop start still tolerates unset roles
- **IF** some or all roles are unset when `/opsx-loop <change>` starts
- **THEN** THE extension SHALL still arm the loop (exporting unset/default
  as today); only `opsx_dispatch` for an unset role refuses

### Requirement: Review Role Auto Fan-Out

THE opsx-loop extension SHALL, WHILE a loop is armed and the `review` role
resolves to a multi-value list and WHEN `opsx_dispatch` is invoked with
`role: "review"`, dispatch one blind subagent spawn per list entry in list
order, each forced to that entry's model id.

#### Scenario: Multi-review list fans out
- **WHILE** `OPSX_REVIEW_MODELS` (or the resolved review list) contains two
  or more model ids
- **WHEN** `opsx_dispatch` is invoked with `role: "review"` and a task
- **THEN** THE extension SHALL spawn exactly one subagent per list entry,
  preserving order, each with that entry's model id

#### Scenario: Single review entry spawns once
- **WHILE** review resolves to exactly one model id
- **WHEN** `opsx_dispatch` is invoked with `role: "review"`
- **THEN** THE extension SHALL spawn exactly one subagent with that model id

### Requirement: Dispatch Spawns Via Subagent Library

WHEN `opsx_dispatch` performs a spawn, THE opsx-loop extension SHALL invoke
the pi-subagents programmatic spawn API as a library consumer (not by
re-registering or same-name-overriding the `subagent` tool, and not by
teaching pi-subagents OPSX role names or `OPSX_*` keys). Pi-subagents SHALL
remain OPSX-blind.

#### Scenario: Spawn uses library path with forced model
- **WHEN** `opsx_dispatch` accepts a configured role and task
- **THEN** THE extension SHALL spawn via the subagent package's programmatic
  API with the forced model id

#### Scenario: Pi-subagents stays OPSX-blind
- **WHEN** the pi-subagents package is inspected for this change
- **THEN** it SHALL NOT gain requirements to read `OPSX_*`, `models.yaml`,
  or opsx role names

## MODIFIED Requirements
<!-- none — Loop exports resolved role models remains; this change adds
mechanical bind on top of export. -->

## REMOVED Requirements
<!-- none -->

## RENAMED Requirements
<!-- none -->

---

## Acceptance criterion quality checklist

| AC ID | Testable | Solution-free | Unambiguous | Consistent | Complete |
|---|---|---|---|---|---|
| opsx-loop.armed-loop-mutes-generic-subagent-tool | [x] | [x] | [x] | [x] | [x] |
| opsx-loop.opsx-dispatch-forces-resolved-role-model | [x] | [x] | [x] | [x] | [x] |
| opsx-loop.review-role-auto-fan-out | [x] | [x] | [x] | [x] | [x] |
| opsx-loop.dispatch-spawns-via-subagent-library | [x] | [x] | [x] | [x] | [x] |
