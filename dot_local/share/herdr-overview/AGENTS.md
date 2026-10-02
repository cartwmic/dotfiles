# Herdr overview runtime — agent instructions

## Scope and authority

This file covers the source-managed Herdr plugin in `dot_local/share/herdr-overview/`.
The repo-root `AGENTS.md` controls chezmoi source, apply, secrets, and commits.
Use this file for changes to the plugin model, pane, presenters, naming, or
recap coordinator. `README.md` here owns desktop setup and human navigation.
The standalone recap store and Pi publication adapter have their own guides;
do not move their logic into this plugin.

## Workflow

- Keep the public Herdr **0.9.1 / protocol 22** boundary in `src/herdr-api.mjs`.
  A server with another protocol fails closed. `herdr-plugin.toml` owns the
  startup, event, pane, and action hooks. The viewer joins native snapshot,
  supplied prompts, published recaps and verified UUID-keyed digests; never
  scrape transcripts, raw terminal tails or generate viewer summaries. The
  `install-herdr-overview` mise task
  links the manifest. The startup hook runs on server start. The
  `herdr plugin action invoke overview.reconcile --plugin overview` action
  loads the linked plugin on a compatible running server without a view.
  `overview.open` opens the shared temporary 100% native popup, with no pane ID.
  Modal `ui_busy` is native. Deleting the owner tab dismisses it; ordinary
  reopening is not survival/resurrection. A vanished non-owner selection must
  notice/refuse unrelated focus while its popup lives. Startup/events/reconcile
  must not open a view. Ask the owner before restarting that server.
- Keep native pane IDs as model keys. If `pane.move` rekeys one, use a unique
  live terminal ID to carry its prompt, manually sourced recap, and naming
  ownership. Do not borrow the UI-focused pane for a publication. Check
  `src/model.mjs`, `src/pane.mjs`, and their tests before changing this join.
- Preserve manual pane and tab labels. `src/display-name-policy.mjs` may
  auto-name an eligible pane from its verified current stable Pi session name
  or stable native subject, never recap/digest bodies;
  `overview.auto_name_pane` and `overview.auto_name_tab` explicitly return
  individual labels to automatic control. One-pane tabs use their stable
  subject; short two-pane subjects combine, otherwise first + N more counts
  remaining live panes. Verified metadata wins; native-title parsing is
  naming-only fallback, never a digest/session identity heuristic. Honest
  generic non-Pi subjects are supported. Recheck live labels before writing.
  Herdr has no atomic conditional rename, so document any residual race.
  Workspace names and Pi identity stay owner-controlled.
- Choose the data path before changing recap behavior: the overview adapter
  owns private real-user prompts under Herdr overview data and consumes native
  Pi saved recaps. The independent Pi recap extension owns generation/settings;
  `session-recap` owns generic records. Read `metadata.pi.sessionId` (also
  accepting `nativeSessionId`) for the native-session join, not history/source
  keys. Project `annotations.herdr` into legacy native fields only in memory;
  never mutate narrative/coverage. Retain legacy records and prompt reading.
  Unannotated new records wait for consumption; session-only annotations cannot
  generate workspace groups. A successful attributed publication resets a
  30-second quiet deadline attributed to that workspace. A later pane move does not reassign
  the deadline. At expiry, grouping uses **current** native pane membership,
  including exact live manually sourced non-Pi pane recaps. Closed panes are
  excluded. Failed grouping leaves prior good records intact and the
  deadline due for a later wake-up; it cannot trigger a session group.
  When `auto_publish = false`, preserve deadlines and pane associations but
  suppress group generation and wake-ups. This generic CLI policy controls
  plugin groups only; never import it into Pi recap settings or generate Pi
  recaps here. A later reconcile after opt-in can
  process due work. Rendering, focus, scrolling, and output refresh must
  remain passive. `overview.refresh_names` is passive too: it neither opens
  nor advances publication/group deadlines; Pi `session_info_changed` uses it.
- The responsive popup map lives in `src/presenters/map.mjs`. Board/Mosaic
  are retired compatibility surfaces, not public layouts. Keep full-name,
  recap, digest and failure boundaries separate. The palette fixture
  `src/palette-v0.9.1.json` is copied from `herdrdev/herdr` tag `v0.9.1`,
  commit `8544776216a8d28088db59a5344ea21ee2d05d2b` (`src/app/state.rs`,
  `Palette` constructors and `Palette::from_name`). Keep Reset and ANSI tokens
  typed. The theme adapter reads the managed config and does not infer host
  appearance without explicit input. A desktop narrow PTY is a layout check;
  Termux-over-SSH proof needs an attended phone client. Termux does not host
  this plugin.

## Deployment from worktrees

The `install-herdr-overview` mise task resolves the configured chezmoi source,
even when launched from a feature worktree. Use the isolated-server journey
below to validate worktree changes. For live rollout, first merge into the
configured source checkout, obtain approval, and follow the setup task in
`README.md` there. Check its source manifest and the registry's `plugin_root`
refer to that approved checkout:

```sh
chezmoi source-path "$HOME/.local/share/herdr-overview/herdr-plugin.toml"
jq -r '.[] | select(.plugin_id == "overview") | .plugin_root' \
  "${XDG_CONFIG_HOME:-$HOME/.config}/herdr/plugins.json"
```

These two reads deliberately inspect the configured source and live registry.
A registry entry pointing elsewhere requires an owner decision; the installer
refuses to replace it. Do not claim the task tested or deployed a feature worktree.
Linking is offline. On an existing compatible server, the reconcile action
listed above loads the linked plugin without requiring a restart; reload config
separately for a changed keybinding.

## Validation

From the chezmoi source root, run the local package and outside-in portable
checks. Node comes from the desktop mise setup; package tests need no live
Herdr server or recap credentials.

```sh
npm test --prefix dot_local/share/herdr-overview
python3 tests/herdr-overview/proof.py recap
python3 tests/herdr-overview/proof.py review
python3 tests/herdr-overview/proof.py chezmoi-dry-run
```

For startup, presenter navigation, or native-pane behavior changes, require
an isolated-server journey after the portable checks. The popup entry is
`python3 tests/herdr-overview/map_journey.py --scenario all --receipts NEW_PRIVATE_DIR`.
It composes completed interactions and identity/publication assertions on one
owned server, preserving lifecycle boundaries. Focused `interactions` and
`identity` scenarios diagnose failures; `smoke` alone is not acceptance. Use a
private interpreter with `pyte==0.8.2` from
`tests/herdr-overview/requirements-interactions.txt` (checked task environment:
`/tmp/hm-pyte-t4a/bin/python`); use it also for `unittest discover -s
tests/herdr-overview -p 'test_*.py'`. Preserve private failure receipts and
current-frame assertions. For true wide geometry detach the narrow peer;
clients share the native popup PTY size. Source-only test fixtures must contain
synthetic names/prompts/bodies, never private real session content.

The reusable fixture commands use attached clients for the same transient
popup, not native pane reads/keys or preset switching:

```sh
python3 tests/herdr-overview/proof.py herdr-prepare
# Copy the run_id from its PASS JSON into RUN_ID below.
python3 tests/herdr-overview/proof.py herdr-wide --run-id RUN_ID
python3 tests/herdr-overview/proof.py herdr-cleanup --run-id RUN_ID
```

Use the same `--state-base` on every command if overriding the private cache
root. Run cleanup for that fixture even after a failed journey; preserve its
failure receipt. For grouping changes, run `python3 tests/herdr-overview/proof.py pi-grouped --run-id RUN_ID`
after `herdr-wide` and before cleanup. That scenario starts
the scripted Pi provider and releases its response gate. For a native-move
claim, keep the prepared fixture alive and follow the attended phone route in
`termux/README.md` (Herdr overview acceptance). With owner authorization, run
`herdr-overview-proof RUN_ID macbook` in Termux. Back on the desktop, validate
its receipt, then move the pane, then clean up:

```sh
python3 tests/herdr-overview/proof.py termux-ssh --run-id RUN_ID
python3 tests/herdr-overview/proof.py herdr-native-move --run-id RUN_ID
python3 tests/herdr-overview/proof.py herdr-cleanup --run-id RUN_ID
```

Read `proof.py --help` and any BLOCKED reason. A missing phone receipt or
scripted provider leaves native-move unproved; clean up the isolated run and
report the gap. Do not restart an owner's server or synthesize a phone
receipt. The first-response move fixture is
`tests/herdr-overview/first_response_move.py`; Herdr's old pane ID can reject
`agent prompt --wait` after a move, so that fixture submits without `--wait`
and observes publication.

## Completion and handoff

Report the source paths changed, protocol and identity behavior touched,
package and proof commands actually run, and any untested real-server or phone
path. State whether a source apply, plugin link, or server restart was left
for the owner. Do not claim a local narrow PTY proved the phone SSH route.
