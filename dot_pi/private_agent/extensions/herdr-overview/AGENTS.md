# Herdr overview Pi adapter — agent instructions

## Scope and authority

This file covers `dot_pi/private_agent/extensions/herdr-overview/`. Repository
`AGENTS.md` controls chezmoi operations; the parent extensions README controls
shared Pi procedure. The local README owns setup. Pi `recap` owns generation,
settings and coverage; the CLI owns generic records. This adapter owns private
prompts/native membership; the Herdr plugin owns overview/grouping.

## Workflow

- Hold serializable state only. Never retain `ctx` after its callback.
- Accept real TUI/RPC input, not extension-generated continuations. Own atomic
  mode-0600 prompt files in Herdr overview data. Final public `agent_settled`
  with no `ctx.hasPendingMessages()` marks the matching prompt settled without
  reading/generating an assistant recap. Do not require `ctx.isIdle()` inside
  this hook: modern Pi counts awaited settlement hooks as streaming.
- Refresh caller-aware `pane.current` via inherited `HERDR_PANE_ID` on input,
  settlement, return and before annotation. Missing socket/pane/workspace stays
  session-only. Never substitute UI focus, alter Pi identity or edit
  `herdr-agent-state.ts`.
- Consume `recap:saved` and startup/return records through generic CLI
  `list/read/annotate`. Events are hints; read authoritative saved records.
  Join native sessions through `metadata.pi.sessionId` (also accept
  `nativeSessionId`), never through the independent history/source key.
- Write only `annotations.herdr` membership. Do not rewrite narrative, coverage,
  source identity or existing publication attribution after move/return.
  Wake `overview.reconcile` after durable annotation. A missed wake-up remains
  recoverable on startup/return. Do not generate Pi recaps, invoke managed
  prepare/publish/prompt commands, or import old CLI auto/backend preferences.
- Keep private current session identity/name publication independent of recap
  generation. Join by socket and unique live terminal, refresh on session lifecycle
  replacement/reload and `session_info_changed`, using actual public UUID/name
  from per-call `ctx` before awaits. Name-only refresh invokes passive
  `overview.refresh_names`, not recap-enabled reconcile. Only TUI/RPC publish;
  print/JSON children must neither claim nor retire interactive records.
  Keep generation/revision guards and compare-owned retirement. Reader joins
  require live publisher, unique native terminal, correct socket and no
  duplicate/conflicting session record. Do not infer session identity
  from recap/digest text or focused panes. The popup reads UUID-keyed dated
  digests separately; rendering must not generate them.
- Desktop profiles only; Termux reaches the desktop through SSH.

## Validation

From the source root:

```sh
node --test dot_pi/private_agent/extensions/herdr-overview/index.test.ts
npm test --prefix dot_local/share/herdr-overview
# After repo preflight, with explicit worktree source:
chezmoi --source "$REPO" apply --dry-run --verbose ~/.pi/agent/extensions/herdr-overview
```

The adapter suite drives real Pi RPC with a scripted provider, real generic
CLI reads/annotations, and a fake protocol-22 socket. It checks prompt/rekey,
saved/startup/return recovery, missing socket and missed wake-up without paid
models or owner processes. The driver owns the full isolated-server proof.
For a visible TUI change, load the pi-tui-scenario-tests skill and require an
outside-in disposable journey. Unit/RPC checks do not prove phone/native moves.

## Completion and handoff

Name source paths, actual checks and pending dry-runs/live journeys. No live
apply, link, restart, commit or phone claim without separate approval.
