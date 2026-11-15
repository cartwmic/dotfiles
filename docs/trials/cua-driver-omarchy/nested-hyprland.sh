#!/bin/sh
# Start a NESTED Hyprland (a window inside the live session) with the scratch config nested.lua, load the Cua
# plugin into it only, enable the plugin, and start a Cua Driver daemon bound to it.
#   usage: nested-hyprland.sh up | down | env
# After `up`, `eval "$(nested-hyprland.sh env)"` points hyprctl and the driver at the nested instance ONLY.
# Never call bare hyprctl/wtype/wlrctl in the same shell without that env: they would hit the live desktop.
set -eu
ROOT="${CUA_TRIAL_DIR:-$HOME/.cache/cua-driver-trial}"; HERE="$(cd "$(dirname "$0")" && pwd)"
V="${CUA_VERSION:-0.51.5}"; ARCH=$(case "$(uname -m)" in aarch64) echo arm64 ;; *) echo x86_64 ;; esac)
CUAD="$ROOT/src/cua-driver-rs-$V-linux-$ARCH/cua-driver"
PLUGIN=$(echo "$ROOT"/src/plugin/cua-hyprland-plugin-*/build/cua-hyprland-plugin.so)
CFG="$ROOT/nested/nested.lua"
case "${1:-}" in
up)
  mkdir -p "$ROOT/nested"; cp "$HERE/nested.lua" "$CFG"
  LIVE_SIG=$(hyprctl instances | sed -n 's/^instance \(.*\):$/\1/p' | head -1)
  (unset HYPRLAND_INSTANCE_SIGNATURE; WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-1}" setsid nohup Hyprland -c "$CFG" >"$ROOT/nested/nested.log" 2>&1 &)
  # The nested compositor takes about a minute to show its window and open its socket.
  i=0; NSIG=""; while [ $i -lt 90 ]; do
    NSIG=$(hyprctl instances | sed -n 's/^instance \(.*\):$/\1/p' | grep -v "^$LIVE_SIG$" | head -1 || true)
    # ready = the nested instance answers with real JSON (its socket exists) and its window is mapped in the live one
    if [ -n "$NSIG" ] && HYPRLAND_INSTANCE_SIGNATURE=$NSIG hyprctl -j monitors 2>/dev/null | grep -q '^\[' \
       && HYPRLAND_INSTANCE_SIGNATURE=$LIVE_SIG hyprctl -j clients | grep -q '"class": "aquamarine"'; then break; fi
    NSIG=""; sleep 2; i=$((i+1)); done
  [ -n "$NSIG" ] || { echo "nested Hyprland did not come up" >&2; exit 1; }
  NWL=$(hyprctl instances | awk -v s="$NSIG" '$0 ~ s {f=1} f && /wl socket/ {print $3; exit}')
  printf 'export HYPRLAND_INSTANCE_SIGNATURE=%s\nexport WAYLAND_DISPLAY=%s\nexport CUA_DRIVER_RS_ENABLE_WAYLAND=1\n' "$NSIG" "$NWL" >"$ROOT/nested/env.sh"
  . "$ROOT/nested/env.sh"
  # The nested window opens fullscreen on the live workspace: float and shrink it.
  A=$(HYPRLAND_INSTANCE_SIGNATURE=$LIVE_SIG hyprctl -j clients | python3 -c 'import json,sys; print([c["address"] for c in json.load(sys.stdin) if c["class"]=="aquamarine"][-1])')
  HYPRLAND_INSTANCE_SIGNATURE=$LIVE_SIG hyprctl dispatch "hl.dsp.window.fullscreen({mode=0, action='unset', window='address:$A'})" >/dev/null
  HYPRLAND_INSTANCE_SIGNATURE=$LIVE_SIG hyprctl dispatch "hl.dsp.window.float({action='enable', window='address:$A'})" >/dev/null
  HYPRLAND_INSTANCE_SIGNATURE=$LIVE_SIG hyprctl dispatch "hl.dsp.window.resize({x=900,y=600,exact=true, window='address:$A'})" >/dev/null
  hyprctl plugin load "$PLUGIN"
  echo 'hl.config({plugin = {cua = {enabled = true}}})' >>"$CFG"; hyprctl reload
  sleep 2; hyprctl -j cua:status | python3 -c 'import json,sys; d=json.load(sys.stdin); print("abi match:", d["abi"]["match"], "state:", d["state"])'
  (setsid nohup "$CUAD" serve >"$ROOT/nested/serve.log" 2>&1 &)
  sleep 3; "$CUAD" call health_report '{}' | python3 -c 'import json,sys; print("health:", json.load(sys.stdin)["overall"])'
  ;;
env) cat "$ROOT/nested/env.sh" ;;
down)
  . "$ROOT/nested/env.sh"
  "$CUAD" stop || true
  hyprctl plugin unload "$PLUGIN" || true
  hyprctl dispatch 'hl.dsp.exit()' || true      # exits the NESTED instance only (signature from env.sh)
  ;;
*) echo "usage: $0 up|down|env" >&2; exit 2 ;;
esac
