# Cua Driver trial on Omarchy (Hyprland, aarch64)

Trial of trycua/cua `libs/cua-driver` (release `cua-driver-rs-v0.51.5`) against the 14 rows in
`~/.local/share/coordinator/workstreams/read-agent-desktop/CUA-CRITERIA.md`. A trial is not adoption: nothing here
is wired into chezmoi, nothing is on PATH, and `~/.local/bin/agent-desktop` is unchanged.
Results: `~/.local/share/coordinator/workstreams/read-agent-desktop/poc-cua/omarchy.md`.

Profile coverage: personal Linux (Omarchy) only. The work profile has no Linux desktop and the work Mac is
never touched, so no work-profile counterpart exists.

## What the trial changes on the host
| Change | Where | Undo |
|---|---|---|
| Driver 0.51.5 (aarch64) and the Hyprland plugin source + build | `~/.cache/cua-driver-trial/` | `undo.sh` |
| Driver daemon state, socket, telemetry id (telemetry disabled) | `~/.cache/cua-driver/`, `~/.cua-driver/` | `undo.sh` |
| A nested Hyprland window and its scratch config | `~/.cache/cua-driver-trial/nested/` | `undo.sh` (`nested-hyprland.sh down`) |
| The plugin loaded into the NESTED compositor only (never the live one) | in memory | `hyprctl plugin unload` / `down` |
| AT-SPI switch `org.a11y.Status IsEnabled` set true (Qt apps started with `QT_ACCESSIBILITY=1` need it) | session bus | `busctl --user set-property org.a11y.Bus /org/a11y/bus org.a11y.Status IsEnabled b false` |

## Reproduce
```sh
docs/trials/cua-driver-omarchy/install.sh 0.51.5        # download, verify sha256, extract, build plugin, run its 21 CTests
docs/trials/cua-driver-omarchy/nested-hyprland.sh up    # nested Hyprland + plugin loaded there + driver daemon (~1-2 min)
eval "$(docs/trials/cua-driver-omarchy/nested-hyprland.sh env)"   # now hyprctl and the driver address the nested session only
(QT_ACCESSIBILITY=1 omacalc &)                          # apps started in this shell open in the nested session
python3 -I docs/trials/cua-driver-omarchy/rows/n3.py    # example row script; others in rows/
```
`cua.py` is a thin wrapper around `cua-driver call` that prints JSON plus per-call milliseconds. Row scripts write
screenshots to the poc-cua evidence folder (edit `E` at the top to change it).

## Gotchas learned
- Set `CUA_DRIVER_RS_ENABLE_WAYLAND=1` for the daemon, or it uses XWayland only.
- The driver keeps `session` labels; an ended label cannot be reused. Use `cua.L(name)`.
- Two background input lanes exist. Leaked sessions fill them: `end_session` each label.
- A right-click context menu holds the compositor grab; later foreground calls refuse (`foreground_grab`) until the menu closes.
- Every shell command in the same shell as an agent session must carry the nested env, or `hyprctl`/`wtype` hit the live desktop.
- `up` took 8 s on the last run and about 67 s on the first. Two runs stalled for 3+ minutes (nested process idle after the dmabuf log lines, no window mapped) while earlier nested instances were still running. Killing the stuck process by exact PID and rerunning fixed it. Run `down` first, and check `ps` for leftover `Hyprland -c` processes before `up`.
- Qt apps need `org.a11y.Status IsEnabled` true; `undo.sh` sets it back to false (its original value).
