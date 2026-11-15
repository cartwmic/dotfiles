#!/bin/sh
# Undo everything the Cua Driver Omarchy trial changed on the host. Safe to re-run.
set -eu
ROOT="${CUA_TRIAL_DIR:-$HOME/.cache/cua-driver-trial}"; HERE="$(cd "$(dirname "$0")" && pwd)"
[ -f "$ROOT/nested/env.sh" ] && "$HERE/nested-hyprland.sh" down || true   # unload plugin, stop daemon, exit nested Hyprland
# the driver daemon's own state (socket, logs, telemetry id) lives outside the scratch dir:
rm -rf "$HOME/.cache/cua-driver" "$HOME/.cua-driver"
rm -rf "$ROOT"                                                              # driver, plugin build, nested config
# accessibility switch that Qt apps flip on when started with QT_ACCESSIBILITY=1 (set back to the pre-trial value):
busctl --user set-property org.a11y.Bus /org/a11y/bus org.a11y.Status IsEnabled b false || true
echo "removed. ~/.local/bin/agent-desktop was never touched."
