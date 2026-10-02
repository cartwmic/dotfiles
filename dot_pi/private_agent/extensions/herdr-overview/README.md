# Herdr Overview Pi consumer

## Ownership and setup

This desktop adapter owns real-user prompt files and native Herdr membership.
It never generates Pi recaps or reads the CLI's automatic-publication preference.
The independent `recap` extension owns `/recap`, generation, coverage and Pi
settings. Recap works with this adapter disabled or Herdr stopped.

On `personal` and `axon-work-computer`, explicitly configure Pi using
`/recap settings`. Old CLI backend/auto preferences are not imported. Set up
`dot_pi/private_agent/extensions/recap/README.md` and the native plugin at
`dot_local/share/herdr-overview/README.md` (paths relative to the source root).
Review both extensions before applying them using the repository procedure;
restart/reload Pi only with owner approval. Termux does not host either adapter.

The generic `session-recap` CLI is normally `~/.local/bin/session-recap`;
`SESSION_RECAP_BIN` can override it. Herdr **0.9.1 / protocol 22** supplies
`HERDR_SOCKET_PATH` and `HERDR_PANE_ID` inside a pane.

## Behavior

- Real TUI/RPC user input writes a private, atomic prompt file under
  `${XDG_DATA_HOME:-~/.local/share}/herdr-overview/prompts`. Generated
  continuations cannot replace it. Final idle settlement marks it not working,
  without needing a recap, backend, CLI preference or Herdr connection.
- Caller-aware `pane.current` follows rekeys using the inherited caller ID.
  It refreshes prompt membership on input, settlement and session return.
  Missing socket/pane leaves the prompt session-only, never UI-focused.
- `recap:saved` is a notification, not trusted publication data. The adapter
  reads the authoritative generic record, checks its native Pi session identity
  (`metadata.pi.sessionId`, also accepting `nativeSessionId`), then refreshes
  membership before writing `annotations.herdr = {pane_id, workspace_id}`.
  The independent history/source key is not a native session identifier.
- Startup/return scans saved records for the current native session, recovering
  detached completion and missed notifications. A missing socket records empty
  attribution and remains session-only. Existing attribution is not reassigned
  on return/move; publication time owns the quiet deadline.
- Annotation never rewrites narrative, coverage, settings or source identity.
  After annotation, the adapter invokes `overview.reconcile`. A failed wake-up
  leaves durable records/annotations for later plugin startup or session return.
  It never calls managed `prepare`, `publish`, `prompt` or `create` commands.

The plugin reads these prompt files and generic recaps, while retaining legacy
record/prompt reading. It owns grouping and manual label protection. Pi context
objects are never retained; neither Pi identity nor `herdr-agent-state.ts` changes.

## Validation and troubleshooting

```sh
node --test dot_pi/private_agent/extensions/herdr-overview/index.test.ts
npm test --prefix dot_local/share/herdr-overview
```

Tests drive real Pi RPC with a scripted provider, the generic CLI, and a fake
protocol-22 socket. They cover saved-event/startup/return recovery, prompt rekey,
private files, missing socket, missed wake-up and no duplicate generation.
The driver owns the full isolated-server journey; these checks do not establish
owner-server rollout, a native move journey or phone access.

For missing recaps, check `/recap settings` and `/recap history` first. CLI
`config auto-publish` controls plugin **group generation**, not Pi recap settings.
For a missed overview wake-up, invoke the loaded plugin's `overview.reconcile`
action; no owner-process restart is implied.
