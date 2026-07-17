<!-- authored: in-session -->
# Capability: opsx-skill-integration

## MODIFIED Requirements

### Requirement: Skills honor configured role models

The openspec-loop, openspec-propose, and openspec-apply-change skills SHALL
consult the resolved role models when authoring artifacts (author role) and
dispatching review subagents (review role) and implementation subagents
(impl role). WHILE an `/opsx-loop` session is armed, those skills SHALL
perform role-bound author/review/impl dispatch exclusively through the
`opsx_dispatch` tool (not the generic `subagent` tool with a soft-honored
`model:` argument), and SHALL perform integration bookkeeping
(`loop_hold`, fidelity ledger rows, follow-ups routing, Execution Notes that
live on review.md / follow-ups.md) exclusively through `opsx_bookkeep` —
not via parent `edit`/`write`. WHILE a loop is armed, `author_in_session`
SHALL NOT keep authoring in the parent: judged propose artifacts MUST go
through `opsx_dispatch(author)` when an author model is configured. WHILE no
loop is armed, skills MAY use the generic `subagent` tool, SHALL fall back
to the session model when a role is unset, and SHALL keep today's
`author_in_session` meaning (default true → in-session authoring). WHILE a
loop is armed, an unset role SHALL NOT be silently filled by the session
model on the `opsx_dispatch` path — the skill SHALL treat the refusal from
`opsx_dispatch` as the correct outcome (or avoid calling it for that unset
role). WHILE armed, a multi-model `review` dispatch SHALL be a single
`opsx_dispatch` call with one `task` (or a length-matched `tasks[]`); THE
tool owns native-parallel fan-out — skills SHALL NOT issue N sequential
`opsx_dispatch` or `subagent` calls to simulate multi-review.

#### Scenario: Armed loop routes review through opsx_dispatch
- **WHILE** `/opsx-loop` is armed and `review` models are configured
- **WHEN** a skill dispatches blind review work
- **THEN** it SHALL invoke `opsx_dispatch` with `role: "review"` (fan-out
  owned by the tool as native parallel when the list has multiple models)
  and SHALL NOT call the generic `subagent` tool for that role-bound work

#### Scenario: Armed multi-review is one opsx_dispatch call
- **WHILE** `/opsx-loop` is armed and review resolves to two or more models
- **WHEN** a skill dispatches blind review work
- **THEN** it SHALL make exactly one `opsx_dispatch` invocation for that
  review (passing `task` or length-matched `tasks[]`) and SHALL NOT loop
  callerside over review models

#### Scenario: Armed loop routes impl through opsx_dispatch
- **WHILE** `/opsx-loop` is armed and an `impl` model is configured
- **WHEN** a skill dispatches an implementation subagent
- **THEN** it SHALL invoke `opsx_dispatch` with `role: "impl"` and SHALL NOT
  rely on soft-honoring `model:` on `subagent`

#### Scenario: Armed loop routes author through opsx_dispatch
- **WHILE** `/opsx-loop` is armed and an `author` model is configured
- **WHEN** a skill authors judged propose/design/spec artifacts
- **THEN** it SHALL invoke `opsx_dispatch` with `role: "author"` and SHALL
  NOT author those artifacts in the parent session via `edit`/`write`,
  regardless of `author_in_session`

#### Scenario: Armed loop routes bookkeeping through opsx_bookkeep
- **WHILE** `/opsx-loop` is armed
- **WHEN** a skill needs to set `loop_hold`, append a fidelity ledger row, or
  route follow-ups on the integration checkout
- **THEN** it SHALL invoke `opsx_bookkeep` and SHALL NOT use parent
  `edit`/`write` for those files

#### Scenario: Disarmed sessions keep generic subagent path
- **WHILE** no loop is armed and an `impl` model is configured
- **WHEN** a skill dispatches an implementation subagent
- **THEN** it MAY use the generic `subagent` tool with the configured impl
  model passed through

#### Scenario: Dispatch honors the resolved provider
- **WHEN** a skill dispatches a review or impl subagent (armed via
  `opsx_dispatch`, or disarmed via `subagent`) and the resolved value is
  provider-qualified (`<provider>/<id>`)
- **THEN** the dispatch SHALL pass the provider-qualified value so the
  subagent runs on the configured provider

#### Scenario: Disarmed authoring stays in-session when author_in_session true
- **WHILE** no loop is armed and `author_in_session` is true or unset
- **WHEN** a skill authors artifacts (even if an `author` model is configured)
- **THEN** it SHALL author in the parent session and SHALL NOT require
  `opsx_dispatch(author)`

#### Scenario: Unset roles — disarmed preserve session fallback
- **WHILE** no loop is armed
- **IF** a role is unset at every layer
- **THEN** the skill SHALL use the session/default model exactly as before
  this change

#### Scenario: Unset roles — armed refuse on opsx_dispatch path
- **WHILE** a loop is armed and a role is unset at every layer
- **IF** the skill would dispatch role-bound work for that role
- **THEN** it SHALL NOT silently substitute the session model; either it
  skips that role or it surfaces the `opsx_dispatch` refusal

### Requirement: Worktree Always Skill Discipline

THE opsx-superpowers skill surfaces SHALL present worktree execution as the
only execution model at every Scale (openspec-loop, openspec-propose,
openspec-apply-change, openspec-archive-change references, openspec-explore):
no skill prose SHALL offer, derive, or describe a same-tree execution path for
opsx-superpowers changes; apply SHALL create/reuse the worktree via
`opsx worktree ensure` before any implementation task at every Scale including
XS; and orchestrator bookkeeping (`loop_hold`, follow-ups.md routing,
Execution Notes) SHALL land on the integration checkout per the
writeback-owner discipline so sealed worktree-bound verdicts stay fresh.
WHILE an `/opsx-loop` session is armed, that integration bookkeeping SHALL be
performed via `opsx_bookkeep` (not parent `edit`/`write`). Placement is not
enforced by prose alone: a bookkeeping commit misplaced onto the
`opsx/<change>` worktree branch moves the verdict-bound HEAD and therefore
STALES the sealed verdicts via the existing range-freshness check — a loud
fail-closed gate red whose remedy is re-review — so a placement violation is
always detected, never silently green.

#### Scenario: Misplaced bookkeeping commit is detected fail-closed
- **WHILE** code-review.md is sealed at the worktree branch HEAD
- **IF** an orchestrator mistakenly commits a follow-ups.md entry on the
  worktree branch instead of the integration checkout
- **THEN** the recorded reviewed range no longer matches the recomputed
  range, the gate SHALL report the verdict stale (fail-closed), and the
  remedy is re-review — the misplacement cannot produce a silently green gate

#### Scenario: XS change runs the full worktree lifecycle
- **WHEN** an XS change is applied
- **THEN** the skill SHALL run ensure → locator capture → apply → review →
  merge → cleanup in an isolated worktree, identical in shape to an M change

#### Scenario: No same-tree guidance survives on skill surfaces
- **WHEN** the canonical opsx-superpowers skill surfaces are inspected
- **THEN** no surface SHALL instruct or permit executing a change's
  implementation directly in the integration checkout

#### Scenario: Armed bookkeeping uses opsx_bookkeep
- **WHILE** `/opsx-loop` is armed
- **WHEN** skills document how to write `loop_hold` or follow-ups routing
- **THEN** they SHALL direct the orchestrator to `opsx_bookkeep` on the
  integration checkout and SHALL NOT instruct parent `edit`/`write` for those
  paths

---

## Acceptance criterion quality checklist

| AC ID | Testable | Solution-free | Unambiguous | Consistent | Complete |
|---|---|---|---|---|---|
| opsx-skill-integration.skills-honor-configured-role-models | [x] | [x] | [x] | [x] | [x] |
| opsx-skill-integration.worktree-always-skill-discipline | [x] | [x] | [x] | [x] | [x] |
