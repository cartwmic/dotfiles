# Herdr Overview plugin runtime

## Overview

This source-managed plugin targets Herdr **0.9.1 / protocol 22**. The desktop
`install-herdr-overview` mise task installs Herdr and links/enables its
manifest on `personal` and `axon-work-computer`. Termux remains an SSH client.
It does not host the plugin. The thin Pi adapter lives at
`dot_pi/private_agent/extensions/herdr-overview/`.

Linking leaves the running server untouched. On a compatible server start,
the plugin's `[[startup]]` hook opens one overview tab and initializes its
model. If a prior plugin process died during a server restart, it closes the
stale plugin-owned shell pane only while that dedicated tab remains intact.
The `overview.reconcile` action uses the same initializer for an already-loaded
server. Chezmoi apply and bootstrap never restart the owner's main server.

The plugin reads native Herdr pane state and recent output through the public
protocol. It joins supplied Pi prompts and published `session-recap` records to
those panes, keeping prompt, recap, and live agent state separate. A pane move
can rekey its native ID; a verified live terminal identity keeps its supplied
prompt and recap visible after the move. Reads never generate recaps. The
[component agent guide](./AGENTS.md) covers ID joins, hooks, and tests.

## Setup

On a `personal` or `axon-work-computer` desktop, review the managed files,
apply them, then run the pinned installer/link task from the chezmoi source
checkout:

```sh
chezmoi apply --dry-run --verbose ~/.local/share/herdr-overview
chezmoi apply ~/.local/share/herdr-overview
mise run install-herdr-overview
```

The task links the plugin without starting or restarting Herdr. Start or
restart a compatible Herdr server yourself, then run `herdr` in a desktop
terminal to attach and open the overview tab. An already running server loads
newly linked plugin code only after that restart. If it has already loaded the
plugin, reconcile the pane and model with:

```sh
herdr plugin action invoke overview.reconcile --plugin overview
```

For desktop provisioning, see `README.md` (Herdr overview and phone route) at
the chezmoi source root. To supply recaps, set up the standalone CLI using
`dot_local/share/session-recap/README.md`. Pi publication setup is in
`dot_pi/private_agent/extensions/herdr-overview/README.md`. These paths are
relative to the source root. The plugin supplies the view and grouping
coordinator; a compatible server and recap backend are separate prerequisites.
The standalone CLI also works with Herdr stopped.

## Usage

The pane selects the narrow Board when its width is at or below `[ui].mobile_width_threshold` in Herdr `config.toml` (the managed value is 64); wider terminals get the independent Mosaic. There is no runtime layout switch. Each presenter owns its all-workspaces, workspace, and pane-detail rendering over the same ID-keyed model.

- Board: summary-first workspaces, then scrollable tab-grouped pane tiles and recent-output-first detail.
- Mosaic: all-workspace/all-pane simultaneous preview, then a tab-grouped preview grid and pane detail.
- `j`/`k` moves through workspaces or panes; `[`/`]` selects tabs; `Enter` opens the next level; `Esc` returns; `f` focuses the selected native pane; `q` closes; `r` rereads saved overview state. In pane detail, `j`/`k`, Space, and `b` scroll.

The display is passive: it shows only supplied prompt fields and published recap records, with age and missing/failure status. Opening, selection, preview refresh, scrolling, and focus never run `session-recap` or synthesize recap text. `overview.reconcile` remains a separate plugin action for publication coordination and manual-library refresh. To show a manually generated single recap in a pane's detail, use that native pane ID as the source ID, for example `printf '%s\n' 'Recent work and current state.' | session-recap create --kind single --source-id PANE_ID`, then invoke `herdr plugin action invoke overview.reconcile --plugin overview` while the source pane is live. This lets the overview display its published or failed status and persist the live terminal association used if `pane.move` later rekeys the pane. Manual results are not Pi auto-naming inputs.

A successful Pi recap starts or resets a 30-second quiet period for its
workspace at publication time. At expiry, grouping uses the latest published
recaps for panes in that workspace's **current** native membership, including
manually sourced recaps for non-Pi panes; closed panes are excluded. A
successful workspace group can produce an active Herdr-session group. A failed
group preserves the last good record and cannot trigger a session group.
Pending deadlines resume after restart. Raw non-Pi output is never included.

Unlabelled panes and Herdr's positional numeric tab defaults may be named from
native titles, agent/process metadata, cwd, and eligible published Pi recaps.
Unknown initial labels and owner edits stay manual. The scoped
`overview.auto_name_pane` and `overview.auto_name_tab` actions return one label
to automatic control. Pi names require a successful recap published for that
pane in its workspace. Workspace names and Pi identity stay untouched. A tab
can combine its pane task labels. Reconciliation rereads a target before an
automatic rename; Herdr 0.9.1 has no conditional rename, so a manual edit in
the final snapshot-to-write interval can still race.

The theme adapter uses Herdr 0.9.1's pinned palette, reads the managed
`config.toml` on pane open, and watches for changes. It resolves `[theme].name`
and `[theme.custom]` when `auto_switch = false`. With `auto_switch = true`, it
needs an explicit appearance input; it does not detect host appearance by
itself. Palette provenance and adapter tests are in the
[component agent guide](./AGENTS.md).

## Troubleshooting

- Linked plugin, missing overview tab: the running server has not loaded the
  startup hook. Start or restart the compatible server intentionally. The
  reconcile action works once the plugin has loaded.
- Missing or failed recap: the overview still shows native pane details.
  Check the recap command and authentication in
  `dot_local/share/session-recap/README.md` and Pi publication setup in
  `dot_pi/private_agent/extensions/herdr-overview/README.md`.
- Real-server proof needs an isolated socket and cleanup. Use
  `python3 tests/herdr-overview/proof.py --help` for its scenarios; the phone
  journey requires an attended Termux-over-SSH client.

## Validation

From the chezmoi source root, run the package tests and the standalone
recap/review checks:

```sh
npm test --prefix dot_local/share/herdr-overview
python3 tests/herdr-overview/proof.py recap
python3 tests/herdr-overview/proof.py review
python3 tests/herdr-overview/proof.py chezmoi-dry-run
```

For isolated real-server and first-response-move fixtures, see
[AGENTS.md](./AGENTS.md). Phone proof needs an attended Termux-over-SSH client
and its returned receipt; a local narrow PTY does not establish that route.
