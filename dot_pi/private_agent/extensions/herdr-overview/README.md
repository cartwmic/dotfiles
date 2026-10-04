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
`SESSION_RECAP_BIN` can override it. Herdr supplies
`HERDR_SOCKET_PATH` and `HERDR_PANE_ID` inside a pane.

## Behavior

- Real TUI/RPC user input writes a private, atomic prompt file under
  `${XDG_DATA_HOME:-~/.local/share}/herdr-overview/prompts`. Generated
  continuations cannot replace it. Final public settlement with no queued input
  marks it not working, without needing a recap, backend, CLI preference or
  Herdr connection. Pi counts awaited settlement hooks as busy, so the guard
  uses public `hasPendingMessages()`, not `isIdle()` inside the hook.
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
  After annotating, the adapter invokes `overview.reconcile` once per pass (not
  per record). Herdr caps concurrent plugin commands at 32, so a full table is
  retried briefly (up to three times) instead of being reported. A failed wake-up
  leaves durable records/annotations for later plugin startup or session return.
  It never calls managed `prepare`, `publish`, `prompt` or `create` commands.

The adapter publishes private current identity/name metadata independently of
recap generation in `$XDG_STATE_HOME/herdr-overview/pi-sessions`, using the actual
per-call public Pi UUID/name and caller-resolved live socket/terminal. Only TUI
and RPC modes publish: text-print/JSON children cannot take over or retire the
interactive binding. Session replacement/reload creates a fresh generation;
compare-owned retirement prevents an old publisher from deleting its successor.
`session_info_changed` refreshes metadata and calls passive
`overview.refresh_names`, not recap-enabled `overview.reconcile`: no model work
is caused by changing names or viewing.

The reader requires one live publisher and one uniquely matching native
terminal on the correct socket, with no conflicting native UUID or duplicate
record. Names/recap/digest BODY, title and cwd cannot infer digest identity.
The popup reads only `.pi/session-search/digests/<verified-UUID>.json`; missing
or malformed dated digests are honestly unavailable. Naming may use an explicit
native Pi title as a naming-only fallback, never as a session/digest join.

The plugin reads private prompt files and generic recaps, while retaining legacy
record/prompt reading. It owns grouping and manual label protection. Pi context
objects are never retained; neither Pi identity nor `herdr-agent-state.ts` changes.
Open the transient native popup using `prefix+shift+o` or `overview.open`; see
`dot_local/share/herdr-overview/README.md` for navigation. Reconcile opens no view.

## Actual questionnaire waiting

The adjacent `question-wait.ts` listens to the installed question package's public
`rpiv:ask-user:blocked` active boolean, not tool names or transcript text. One
idempotent `herdr:blocked` contribution goes to the existing stock native writer.
Only its own `herdr:overview-question` metadata source supplies the blocked reason
`Awaiting answer`, guarded by `applies_to_source = herdr:pi`. Caller-aware terminal
identity, ordered reports and session/wait generations fence late publication.
Answer, cancel and teardown clear only that contribution and its reason labels;
foreign blockers and labels are not cleared. Collapsing the question is not completion.
No long-lived Pi context is retained, and this adapter never reports native agent
state directly or modifies the installed stock integration.

Settlement-abort v1 reported `ctx.isIdle() === false` in final handlers, including
`agent_settled`, which suppressed stock native READY reporting. The v2 patch in
`dot_local/share/pi-patches/settlement-abort` preserves main-agent idle there and is
required; this source never bypasses the native or adapter idle guard.

The maintained question fixture (`tests/herdr-overview/question_wait_journey.py`)
exercises the real installed package with a scripted provider. Its error case renders
and dismisses the actual dialog, then injects a controlled rejection at the public
`ui.custom` completion boundary, exercising the package's real wait/finally cleanup.
It does not fabricate question events. Public reload while a collapsed dialog waits is
refused until idle; new-session waits for the dialog to finish before replacing the
session. Recap timestamps remain producer-owned and are displayed unchanged by Overview.

## Validation and troubleshooting

```sh
node --test dot_pi/private_agent/extensions/herdr-overview/index.test.ts
npm test --prefix dot_local/share/herdr-overview
```

Tests drive real Pi RPC with a scripted provider, the generic CLI, and a fake
protocol-22 socket. They cover saved-event/startup/return recovery, prompt rekey,
private files, missing socket, missed wake-up, no duplicate generation and current
UUID/name publication, replacement/reload/retirement and print-child exclusion.
The driver owns the full isolated-server journey; these checks do not establish
owner-server rollout, a native move journey or phone access.

For missing recaps, check `/recap settings` and `/recap history` first. CLI
`config auto-publish` controls plugin **group generation**, not Pi recap settings.
For a missed overview wake-up, invoke the loaded plugin's `overview.reconcile`
action; no owner-process restart is implied. Missing caller pane/workspace
membership stays session-only and is never borrowed from UI focus.
