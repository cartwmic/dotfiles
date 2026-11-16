# session.sh: find the live Wayland and Hyprland session and put WAYLAND_DISPLAY and HYPRLAND_INSTANCE_SIGNATURE in the
# environment. Source it; do not run it. POSIX sh and zsh. Source: dot_local/share/agent-desktop/session.sh, personal Linux
# only (docs/profiles.md). Docs: README "Linux on Arch (Omarchy)".
#
# One place for the lookup. Three callers source it: dot_zshenv (every agent shell), agent-desktop and agent-chrome.
#
# Why: t3code.service starts before Hyprland, so an agent shell inherits neither variable and `grim` ("failed to create
# display") and `hyprctl` ("HYPRLAND_INSTANCE_SIGNATURE not set!") fail. The signature changes on every Hyprland start, so a
# fixed value in the unit would go stale; each shell looks it up when it starts.
#
# How: $XDG_RUNTIME_DIR/hypr/<signature>/ is one folder per Hyprland start and a crashed or restarted one is left behind.
# A folder is live when its hyprland.lock names a pid that is still running (the lock holds the pid on line 1 and the
# WAYLAND_DISPLAY name on line 2) and its .socket.sock is a socket. Among live folders the newest wins: the signature is
# <hash>_<start epoch>_<n>, compared on the epoch. It reads no process: only globs, `read` and `[ ]`, so it is cheap enough
# for ~/.zshenv. (`id -u` runs only when XDG_RUNTIME_DIR is unset, which a systemd user session never leaves it.)
#
# What is already set: a HYPRLAND_INSTANCE_SIGNATURE whose instance is live is kept, with its WAYLAND_DISPLAY (an unset
# WAYLAND_DISPLAY is filled from that instance's lock). A signature that is unset, or names an instance that is gone (t3code
# started under an earlier Hyprland, then Hyprland restarted), is replaced, together with WAYLAND_DISPLAY, by the newest live
# instance's pair. With no live instance nothing is changed and nothing is printed, so it is safe to call anywhere.

_agent_desktop_session_live() {  # DIR: live when its socket exists and its lock names a running pid; sets _ads_display
  _ads_pid= _ads_display=
  [ -S "$1/.socket.sock" ] && [ -r "$1/hyprland.lock" ] || return 1
  { IFS= read -r _ads_pid; IFS= read -r _ads_display; } <"$1/hyprland.lock" || :
  case $_ads_pid in ''|*[!0-9]*) return 1 ;; esac
  [ -d "/proc/$_ads_pid" ]
}

agent_desktop_session() {
  if [ -n "${ZSH_VERSION-}" ]; then emulate -L sh; fi   # sh word splitting and globs, undone when the function returns
  _ads_run=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
  if [ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ] && _agent_desktop_session_live "$_ads_run/hypr/$HYPRLAND_INSTANCE_SIGNATURE"; then
    if [ -z "${WAYLAND_DISPLAY:-}" ] && [ -S "$_ads_run/$_ads_display" ]; then
      WAYLAND_DISPLAY=$_ads_display
      export WAYLAND_DISPLAY
    fi
    unset _ads_run _ads_pid _ads_display
    return 0
  fi
  _ads_best= _ads_best_epoch=-1 _ads_best_display=
  for _ads_dir in "$_ads_run"/hypr/*; do
    _agent_desktop_session_live "$_ads_dir" || continue
    _ads_sig=${_ads_dir##*/}
    _ads_epoch=${_ads_sig#*_}
    _ads_epoch=${_ads_epoch%%_*}
    case $_ads_epoch in ''|*[!0-9]*) _ads_epoch=0 ;; esac
    if [ "$_ads_epoch" -ge "$_ads_best_epoch" ]; then
      _ads_best=$_ads_sig _ads_best_epoch=$_ads_epoch _ads_best_display=$_ads_display
    fi
  done
  if [ -n "$_ads_best" ]; then
    HYPRLAND_INSTANCE_SIGNATURE=$_ads_best
    export HYPRLAND_INSTANCE_SIGNATURE
    if [ -S "$_ads_run/$_ads_best_display" ]; then
      WAYLAND_DISPLAY=$_ads_best_display
      export WAYLAND_DISPLAY
    fi
  fi
  unset _ads_run _ads_pid _ads_best _ads_best_epoch _ads_best_display _ads_dir _ads_display _ads_sig _ads_epoch
}
