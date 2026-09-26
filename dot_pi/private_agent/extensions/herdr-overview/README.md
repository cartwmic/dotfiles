# Herdr Overview Pi publication adapter

This desktop-only Pi extension supplies the current prompt and publishes a recap after a settled response. It is a thin caller of the portable `session-recap` command; it does not own recap prompts, persistence, grouping, or Herdr overview state.

## Requirements

- The `session-recap` CLI from this dotfiles tree, normally at `~/.local/bin/session-recap`, with its normal configuration and local data directory.
- For Herdr publication-time attribution and wake-up, Herdr **0.9.1 / protocol 22** must be running with the existing Herdr Overview plugin loaded.
- Herdr supplies `HERDR_SOCKET_PATH` and, inside a pane, `HERDR_PANE_ID`. `SESSION_RECAP_BIN` can override the CLI path for a host or test.

The source lives under `dot_pi/private_agent/extensions/`, so it deploys with the desktop Pi extensions. The existing chezmoi `termux` profile skips `.pi` completely; this extension is not installed on Termux. It is a Pi extension, not another Herdr host plugin.

## Lifecycle

- Pi's public `input` event stores text from real interactive (`source: interactive`, TUI mode) and RPC (`source: rpc`, RPC mode) input with `session-recap prompt set`. Extension-generated input is ignored, so continuations do not replace the last real prompt.
- On `agent_settled`, the adapter requires `ctx.isIdle() === true`, marks that prompt settled, and reads the latest assistant message from the public `ctx.sessionManager.getBranch()` API. It does not inspect session files.
- A nonblank response is sent to `session-recap prepare`. Failed or blank backend output is not published and does not wake Herdr.
- Immediately before `session-recap publish`, it calls Herdr's public `session.snapshot` and matches the exact `HERDR_PANE_ID`. The observed `workspace_id` is attached to that publication; missing pane, workspace, socket, or compatible snapshot means publication without workspace attribution.
- After confirmed publication, it invokes only the existing public `plugin.action.invoke` action `overview.reconcile`. A failed wake-up does not undo the durable recap; Herdr startup reconciliation can catch it up.

Duplicate settled events are consumed once per real prompt. Pi context objects are read only during their event callback and are never retained. Pi session identity and Herdr-managed `herdr-agent-state.ts` are untouched.

## Validation

From this directory:

```sh
node --test
```

The tests use a temporary Pi RPC session, a scripted OpenAI-compatible response server, the real T1 `session-recap` CLI with a fake backend, and a fake Herdr protocol-22 socket. No live model or Herdr server is required.
