<!-- authored: in-session -->
# Proposal — opsx-loop-pure-router

## Why

Armed `/opsx-loop` already hard-forces review through `opsx_dispatch` and mutes
generic `subagent`, but parent `edit`/`write` stay live and `author_in_session`
defaults to in-session authoring — so a weak orchestrator can ship session-model
code and skip role models. Pure-router closes that hole: judged writes only via
role-bound dispatch; meta writes only via a narrow structured tool (Constitution
II skill surface + IX multi-model review for skill edits).

## What Changes

- **BREAKING (armed path only):** parent active tool set drops `edit` and `write`
  (plus existing `subagent` mute). Judged propose/impl/review writes MUST go
  through `opsx_dispatch(author|impl|review)`.
- **BREAKING (armed path only):** WHILE armed, ignore `author_in_session` —
  authoring MUST `opsx_dispatch(author)` when author role is configured; unset
  author keeps refuse / no session fallback (never silently parent-author).
- Add `opsx_bookkeep` structured tool: mutate ONLY armed change INTEGRATION
  `review.md` / `follow-ups.md` (schema-validated ops; refuse hold-clear for
  agents; refuse wrong change / worktree-only paths).
- Skills (`openspec-loop`, `openspec-propose`, `openspec-apply-change`): rewrite
  armed-phase tables as MUST-dispatch; prose is routing guidance — enforcement
  is the muted tool surface.
- Hermetic tests: armed mute drops edit/write/subagent + restores on clear;
  `opsx_bookkeep` allow/refuse matrix; armed author override; prior
  mute/unset/sole-source/transparent suite stays green.
- Document accepted shell residual (`bash` can still mutate) as known risk;
  harden deferred (Non-goal).

## Capabilities

### New Capabilities
- (none)

### Modified Capabilities
- `opsx-loop`: Armed mute extends to edit/write; expose `opsx_bookkeep`; armed
  author override; retain bind/mute/unset/transparent contracts.
- `opsx-skill-integration`: Armed MUST-dispatch prose for author/impl/review;
  bookkeep vs judged-write split; disarmed `author_in_session` meaning unchanged.

## Impact

**Affected files (expected):**
- `dot_pi/agent/extensions/opsx-loop/` (`helpers.ts`, `index.ts`, bookkeep
  module/tests)
- `dot_local/share/agent-harness/canonical/skills/openspec-{loop,propose,apply-change}/`
- Delta specs under `openspec/changes/opsx-loop-pure-router/specs/`

**Dependencies:** existing `opsx_dispatch` / pi-subagents spawn path (OPSX-blind).
One-way: opsx-loop → pi-subagents. Does not replace
`opsx-loop-role-dispatch` / `opsx-dispatch-transparent` — extends them.

## Assumptions recorded

- Scale M, `full_rigor: true` per frozen intent (standalone clarify/design/analyze,
  independent doneness, ADR, retrospective).
- Core envelope only: shell argv allowlist, gate provenance, ext auto-stamp,
  phase-scoped tool sets are Non-goals (shell residual accepted + documented).
- Exact host tool name strings for edit/write match whatever pi exposes today
  (`edit` / `write` or successors — design pins literals from `getActiveTools`).
- `opsx_bookkeep` is one tool with an ops enum (not free-path edit); split into
  multiple tools only if design proves one-tool schema unwieldy.
- Disarmed / manual propose keeps today's `author_in_session` default (true).
