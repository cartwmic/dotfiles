# Zellij configuration

Chezmoi-managed config for the [Zellij](https://zellij.dev) terminal multiplexer
(deploys to `~/.config/zellij/`). Includes keybinds, layouts, and a small
plugin set with one custom-patched fork.

## Layout

```
dot_config/zellij/
├── README.md          # This file (deploys to ~/.config/zellij/README.md)
├── config.kdl         # Keybinds, theme, modes
└── (no plugins/ dir — wasm binaries are NOT version-controlled;
                       they're built/downloaded by mise — see below)
```

## Plugins

Two third-party plugins are installed on bootstrap by the mise task
[`install-zellij-plugins`](../mise/config.toml). Wasm binaries land in
`~/.config/zellij/plugins/` with sibling stamp files (`.harpoon.version`,
`.room.version`) for idempotent reinstall.

| Plugin | Source | Keybind | Purpose |
| --- | --- | --- | --- |
| [room](https://github.com/rvcas/room) | upstream prebuilt wasm release | `Ctrl-t` | Fuzzy-jump between sessions/tabs/panes |
| [harpoon](https://github.com/Nacho114/harpoon) | **cartwmic fork**, built from source | `Ctrl-y` | Pin & quick-switch favorite panes |

### Why harpoon is on a fork

Upstream `Nacho114/harpoon` v0.3.0 has a bug: the `a` key (add current pane to
the harpoon list) only ever adds one pane per tab. Two compounding causes:

1. When harpoon (a floating plugin pane) gains focus, its `get_focused_pane`
   fallback returned the first non-plugin pane in the tab, overwriting the
   tracked previous-focus on the next `PaneUpdate`. Subsequent adds always
   re-tried the same first pane and the dedup check silently dropped them.
2. `PaneInfo.is_focused` is documented as "focused in its layer (tiled or
   floating)" but in tabs with splits or stacks it actually flags **multiple**
   non-plugin panes as focused (effectively one per layout-subtree-leaf). A
   naive `find(is_focused)` returns whichever appears first in iteration order
   — not the pane the user is actually on.

The fork [cartwmic/harpoon](https://github.com/cartwmic/harpoon) at commit
`da678cb` fixes both:

- `get_focused_pane` now returns `None` when the floating layer holds focus,
  and `update_panes` keeps `focused_pane` sticky to the most recent real
  terminal-focus event instead of clobbering it.
- Among `is_focused && !is_plugin` panes it picks the highest pane id (zellij
  assigns ids monotonically, so this tracks the most recently created/operated
  pane and matches the user's actual focus in stacked/split layouts).

The fork is pinned by commit SHA in `dot_config/mise/config.toml` via
`HARPOON_REPO` and `HARPOON_VERSION`. Bump both together when re-syncing with
upstream.

## Syncing the harpoon fork with upstream

```sh
cd ~/git/harpoon            # or wherever the fork is cloned
git fetch upstream
git merge upstream/main     # resolve any conflicts on top of the custom patch
git push origin main
git rev-parse HEAD          # copy the new SHA
```

Then in chezmoi:

```sh
$EDITOR ~/.local/share/chezmoi/dot_config/mise/config.toml
# update HARPOON_VERSION="<new SHA>"
chezmoi apply ~/.config/mise/config.toml
mise run install-zellij-plugins   # rebuilds wasm from the new SHA
```

The mise task switches the local clone's `origin` URL on each run, so changing
`HARPOON_REPO` (e.g. back to upstream after the patch lands) just works.

## Reload workflow gotcha

**Replacing `harpoon.wasm` on disk doesn't take effect until the running zellij
session re-reads it.** The zellij server process per session caches the
compiled wasm module in memory — killing and re-launching the *plugin pane*
spawns a fresh instance but reuses the cached module from server memory. The
file on disk is ignored.

To force a re-read, in order of least-disruptive:

1. **Plugin Manager reload** (keeps the session): `Ctrl-o` (session mode) →
   `p` to open Plugin Manager → navigate to the plugin → reload.
2. **Session restart**: detach (`Ctrl-q` or `zellij detach`), then
   `zellij kill-session <name>` and reattach. Loses ephemeral pane state.

Plugin Manager reload is usually enough. If `Ctrl-o p` reload doesn't seem to
apply (open zellij issue
[#3994](https://github.com/zellij-org/zellij/issues/3994) tracks flakiness on
some versions), fall back to session restart.

### Adjacent gotcha: permission-grant on first launch

When a plugin first loads in any session, zellij prompts the user to grant
permissions (e.g. `ChangeApplicationState`, `RunCommands`). If the launcher
keybind fires before the prompt is acknowledged, the plugin pane will render
its UI but actions are silently no-op'd because permissions weren't granted
in time. Permissions are then cached globally at
`~/Library/Caches/org.Zellij-Contributors.Zellij/permissions.kdl` (macOS),
**but the broken pre-grant plugin instance is not retroactively healed**, and
`LaunchOrFocusPlugin` re-focuses the broken instance instead of restarting it.

Fix: close the floating plugin pane (`CloseFocus` while it's focused), then
relaunch — the new instance picks up the cached permissions.

## See also

- `dot_config/mise/config.toml` — `install-zellij-plugins` task definition
- Upstream Zellij docs: <https://zellij.dev/documentation/>
- Zellij plugin API (zellij-tile crate): <https://docs.rs/zellij-tile>
