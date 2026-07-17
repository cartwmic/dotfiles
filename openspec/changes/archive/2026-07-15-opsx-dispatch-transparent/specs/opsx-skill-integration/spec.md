<!-- authored: in-session -->
# Capability: opsx-skill-integration

## MODIFIED Requirements

### Requirement: Skills honor configured role models

The openspec-loop, openspec-propose, and openspec-apply-change skills SHALL
consult the resolved role models when authoring artifacts (author role) and
dispatching review subagents (review role) and implementation subagents
(impl role). WHILE an `/opsx-loop` session is armed, those skills SHALL
perform role-bound review/impl/(opt-in author) dispatch exclusively through
the `opsx_dispatch` tool (not the generic `subagent` tool with a soft-honored
`model:` argument). WHILE no loop is armed, skills MAY use the generic
`subagent` tool and SHALL fall back to the session model when a role is
unset. WHILE a loop is armed, an unset role SHALL NOT be silently filled by
the session model on the `opsx_dispatch` path — the skill SHALL treat the
refusal from `opsx_dispatch` as the correct outcome (or avoid calling it for
that unset role). WHILE armed, a multi-model `review` dispatch SHALL be a
single `opsx_dispatch` call with one `task` (or a length-matched `tasks[]`);
THE tool owns native-parallel fan-out — skills SHALL NOT issue N sequential
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

#### Scenario: Authoring stays in-session regardless of author model
- **WHILE** `author_in_session` is true or unset
- **WHEN** a skill authors artifacts (even if an `author` model is configured)
- **THEN** it SHALL author in the parent session and SHALL NOT dispatch an
  authoring subagent; `author_model` is consumed ONLY for delegated authoring
  when `author_in_session` is false (via `opsx_dispatch` when a loop is armed)

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
