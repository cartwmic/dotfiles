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
  startup, event, pane, and action hooks. Output refresh uses the public
  `pane.output_matched` subscription while a view is open, with an initial
  `pane.read` before its first frame; Herdr plugin hooks omit high-volume
  output events. Close subscriptions on exit. A failed read keeps native
  metadata and the saved preview. The `install-herdr-overview` mise task
  links the manifest. Linking does not load a startup hook into an
  already-running server; ask the owner before restarting that server.
- Keep native pane IDs as model keys. If `pane.move` rekeys one, use a unique
  live terminal ID to carry its prompt, manually sourced recap, and naming
  ownership. Do not borrow the UI-focused pane for a publication. Check
  `src/model.mjs`, `src/pane.mjs`, and their tests before changing this join.
- Preserve manual pane and tab labels. `src/display-name-policy.mjs` may
  auto-name an eligible pane from a successful in-workspace Pi recap;
  `overview.auto_name_pane` and `overview.auto_name_tab` explicitly return
  individual labels to automatic control. Recheck live labels before writing.
  Herdr has no atomic conditional rename, so document any residual race.
  Workspace names and Pi identity stay owner-controlled.
- Choose the data path before changing recap behavior: Pi supplies a prompt
  and a settled publication; `session-recap` owns records; this plugin reads
  them. A successful in-workspace publication resets a 30-second quiet
  deadline attributed to that workspace. A later pane move does not reassign
  the deadline. At expiry, grouping uses **current** native pane membership,
  including exact live manually sourced non-Pi pane recaps. Closed panes are
  excluded. Failed grouping leaves prior good records intact and the
  deadline due for a later wake-up; it cannot trigger a session group.
  Rendering, focus, scrolling, and output refresh must remain passive.
- Board and Mosaic share the model but own separate layouts in
  `src/presenters/`. Change each intentionally. The palette fixture
  `src/palette-v0.9.1.json` is copied from `herdrdev/herdr` tag `v0.9.1`,
  commit `8544776216a8d28088db59a5344ea21ee2d05d2b` (`src/app/state.rs`,
  `Palette` constructors and `Palette::from_name`). Keep Reset and ANSI tokens
  typed. The theme adapter reads the managed config and does not infer host
  appearance without explicit input. A desktop narrow PTY is a layout check;
  Termux-over-SSH proof needs an attended phone client. Termux does not host
  this plugin.

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
an isolated-server journey after the portable checks. From the source root:

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
