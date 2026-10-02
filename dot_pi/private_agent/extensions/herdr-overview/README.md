# Herdr Overview Pi publication adapter

## Overview

This desktop-only Pi extension supplies the current prompt and, when opted in, publishes a recap after a settled response. `session-recap` stores prompts separately from dated recap records; the extension calls its prompt and prepare/publish commands. It does not own recap prompts, persistence, grouping, or Herdr overview state.

## Setup

On a `personal` or `axon-work-computer` desktop, set up the standalone CLI
using `dot_local/share/session-recap/README.md` (paths here are relative to
the chezmoi source root). Managed installs store prompts and start with
automatic recap publication off. Add a host-local command and
`auto_publish = true` in `~/.config/session-recap/config.local.toml` to opt in.
Load the Herdr plugin using `dot_local/share/herdr-overview/README.md` for
workspace attribution and the overview display. Then review and apply this
Pi extension. Restart Pi to load it:

```sh
chezmoi apply --dry-run --verbose ~/.pi/agent/extensions/herdr-overview
chezmoi apply ~/.pi/agent/extensions/herdr-overview
```

- The `session-recap` CLI from this dotfiles tree, normally at `~/.local/bin/session-recap`, with its normal configuration and local data directory.
- For Herdr publication-time attribution and wake-up, Herdr **0.9.1 / protocol 22** must be running with the existing Herdr Overview plugin loaded.
- Herdr supplies `HERDR_SOCKET_PATH` and, inside a pane, `HERDR_PANE_ID`. `SESSION_RECAP_BIN` can override the CLI path for a host or test.

The source lives under `dot_pi/private_agent/extensions/`, so it deploys with the desktop Pi extensions. The existing chezmoi `termux` profile skips `.pi` completely; this extension is not installed on Termux. This code runs inside Pi. The Herdr host plugin lives at
`dot_local/share/herdr-overview/` in chezmoi source.

## Usage

Run Pi inside a Herdr pane and submit an interactive prompt. While Pi works,
the overview inline detail shows that current prompt separately. The prompt
settles even when automatic recaps are off. With `auto_publish = true` and a
working backend, the settled reply also produces a published recap and dated
record. A disabled or failed backend leaves the native pane and prompt
visible. See
`dot_local/share/herdr-overview/README.md` (Usage) for navigation.

- Pi's public `input` event stores text from real interactive (`source: interactive`, TUI mode) and RPC (`source: rpc`, RPC mode) input with `session-recap prompt set`. When `HERDR_PANE_ID` is present, the adapter first calls Herdr's caller-aware `pane.current` and stores the returned live native pane ID, so a pane rekeyed by `pane.move` does not leave the current prompt attached to its old ID. Missing membership leaves the prompt session-only; it is never guessed from UI focus. Extension-generated input is ignored, so continuations do not replace the last real prompt.
- On `agent_settled`, the adapter requires `ctx.isIdle() === true`, marks that prompt settled, and reads the latest assistant message from the public `ctx.sessionManager.getBranch()` API. It does not inspect session files.
- Before preparing a nonblank response, the adapter rechecks `pane.current` through the inherited caller ID. If the pane moved during its first response, `prompt rekey` atomically retargets only the matching current prompt without replacing a newer input or changing its working state; `prepare` records the new native pane ID. Failed or blank backend output is not published and does not wake Herdr.
- Immediately before `session-recap publish`, it calls Herdr 0.9.1's public `pane.current` with `{ caller_pane_id: HERDR_PANE_ID }`. This caller-aware lookup follows a running pane if `pane.move` has rekeyed its native pane ID; it never substitutes the UI-focused pane. The observed `workspace_id` is attached to that publication; missing pane, workspace, socket, or response means publication without workspace attribution.
- After confirmed publication, it invokes only the existing public `plugin.action.invoke` action `overview.reconcile`. A failed wake-up does not undo the durable recap; Herdr startup reconciliation can catch it up.

The adapter publishes private current identity/name metadata independently of
recap opt-in in `$XDG_STATE_HOME/herdr-overview/pi-sessions`, using the actual
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

Duplicate settled events are consumed once per real prompt. Pi context objects are read only during their event callback and are never retained. Pi session identity and Herdr-managed `herdr-agent-state.ts` are untouched.

## Troubleshooting

- No published recap: run `session-recap config auto-publish`. `disabled` is
  expected until the local config opts in. If the policy check errors, fix
  the command/configuration in `dot_local/share/session-recap/README.md`
  (Setup). `SESSION_RECAP_BIN` can override the installed CLI path. Blank or
  failed backend output is recorded without a publication wake-up.
- Recap published but no popup: `overview.reconcile` refreshes the model
  without opening a view. Invoke `herdr plugin action invoke overview.open
  --plugin overview` or use `prefix+shift+o`; see the plugin guide (Setup).
- Recap without a workspace group: the adapter needs live caller pane and
  workspace membership through `HERDR_PANE_ID` and `HERDR_SOCKET_PATH`.
  Missing membership stays session-only; it is never borrowed from UI focus.

## Validation

From this directory:

```sh
node --test
```

The tests drive both the default-off and opted-in Pi RPC paths with a scripted response server, the real `session-recap` CLI, a fake recap backend, and a fake Herdr protocol-22 socket. No live model or Herdr server is required.
