#!/bin/sh
# instances_reconcile.sh: make each instance (coordinator, retro) match its opt-in flag. Run by chezmoi on every apply
# (run_after_75_instances_reconcile.sh.tmpl); it can also be run by hand with the same environment.
#
# Desired state comes from the local chezmoi.yaml (data.instances.<name>.enabled), passed in as INSTANCES_<NAME>_ENABLED.
#   true            opt in: dirs, config (once), the unit file, and start. Everything is idempotent.
#   false or unset  opt out, but only for an instance this script started or adopted (marker). A Mac that never opted in is left alone.
#
# The safety rules, in force on every run:
#   * launchctl is called for exactly: print (read-only, once per enabled or managed instance), bootstrap (the instance is not loaded),
#     bootout (opt out, or a requested reload). A loaded service is never booted out or kicked because a template re-rendered.
#   * A unit file that differs from the one the service was loaded with is REPORTED (reload needed). It is reloaded only when
#     INSTANCES_RELOAD names the instance (or "all") on that run, and only if the unit really changed.
#   * Opt-out never deletes state, config, tokens, playbooks or logs. It removes the unit file and the markers.
#   * Every outcome is one status line and exit 0, so a missing token or room cannot block other chezmoi work. The next run starts over.
#   * Nothing secret is read, printed or stored here. The repos' own scripts own tokens.
#
# Markers: $INSTANCES_STATE_ROOT (default ~/.local/state/instances)/<name>.{managed,unit-sha,seeded,status}.
# Test hooks: INSTANCES_STATE_ROOT, INSTANCES_UNIT_DIR, INSTANCES_AGENTS_DIR, INSTANCES_TOOL_PATH, INSTANCES_LIST, INSTANCES_TIMEOUT.
set -u

# Decision #138 (Michael, pending): does opt-out also close the Pi pane? Today: no. This one line is what gets changed.
PANE_NOTE='the Pi pane keeps running (stopping the daemon does not close it); close it yourself if you want it gone'

HOME_DIR=${HOME:-}
[ -n "$HOME_DIR" ] && [ -d "$HOME_DIR" ] || { echo "[instances] WARN: HOME is not a directory; nothing done" >&2; exit 0; }
STATE_ROOT=${INSTANCES_STATE_ROOT:-$HOME_DIR/.local/state/instances}
UNIT_DIR=${INSTANCES_UNIT_DIR:-$HOME_DIR/.local/share/instances/launchd}
AGENTS_DIR=${INSTANCES_AGENTS_DIR:-$HOME_DIR/Library/LaunchAgents}
# The PATH the units give the daemons; the tools they need must be found on it, not on whatever PATH this script has.
TOOL_PATH=${INSTANCES_TOOL_PATH:-$HOME_DIR/.local/share/mise/shims:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin}
TIMEOUT=${INSTANCES_TIMEOUT:-30}
CONFIG_TIMEOUT=${INSTANCES_CONFIG_TIMEOUT:-120}
DOMAIN="gui/$(id -u)"
TMP=$(mktemp -d "${TMPDIR:-/tmp}/instances.XXXXXX") || exit 0
trap 'rm -rf "$TMP"' EXIT

say() { printf '[instances] %s\n' "$*"; }

with_timeout() { # with_timeout SECONDS CMD ARGS...
  _secs=$1; shift
  if command -v perl >/dev/null 2>&1; then perl -e 'alarm shift; exec @ARGV or exit 127' "$_secs" "$@"; else "$@"; fi
}
first_line() { head -n 1 "$1" 2>/dev/null | cut -c1-200; }
sha() { shasum -a 256 "$1" 2>/dev/null | cut -d' ' -f1; }
have() { # have TOOL: found on the daemon's PATH
  _old=$IFS; IFS=:
  for _d in $TOOL_PATH; do if [ -x "$_d/$1" ]; then IFS=$_old; return 0; fi; done
  IFS=$_old; return 1
}

# launchctl, by name (so a test can put a stub first on PATH). OUT is its combined output.
run_lc() { with_timeout "$TIMEOUT" launchctl "$@" >"$TMP/lc.out" 2>&1; }
probe_loaded() { # sets LOADED=yes|no; returns 1 if launchd cannot be asked
  run_lc print "$DOMAIN/$LABEL"; _rc=$?
  case $_rc in 0) LOADED=yes;; 113) LOADED=no;; *) LC_ERR="launchctl print exited $_rc: $(first_line "$TMP/lc.out")"; return 1;; esac
  return 0
}

load_instance() { # load_instance NAME: sets the per-instance variables
  NAME=$1
  case $1 in
    coordinator)
      LABEL=local.coordinatord; LOGDIR=$HOME_DIR/Library/Logs/coordinator; STATE=$HOME_DIR/.local/share/coordinator
      MAIN=src/coordinatord/main.ts; SETUP=scripts/instance-setup.sh
      ENABLED=${INSTANCES_COORDINATOR_ENABLED:-}; REPO=${INSTANCES_COORDINATOR_REPO:-};;
    retro)
      LABEL=local.retrod; LOGDIR=$HOME_DIR/Library/Logs/retro; STATE=$HOME_DIR/.local/share/retro
      MAIN=src/retrod/main.ts; SETUP=scripts/configure.sh
      ENABLED=${INSTANCES_RETRO_ENABLED:-}; REPO=${INSTANCES_RETRO_REPO:-};;
    *) say "unknown instance $1"; return 1;;
  esac
  SRC=$UNIT_DIR/$LABEL.plist; DST=$AGENTS_DIR/$LABEL.plist
  M_MANAGED=$STATE_ROOT/$NAME.managed; M_SHA=$STATE_ROOT/$NAME.unit-sha; M_SEEDED=$STATE_ROOT/$NAME.seeded; M_STATUS=$STATE_ROOT/$NAME.status
}

finish() { # finish MESSAGE: the one status line of this instance
  say "$NAME: $1"
  mkdir -p "$STATE_ROOT" 2>/dev/null && printf '%s\n' "$1" >"$M_STATUS" 2>/dev/null
  return 0
}

reload_requested() {
  case ",$(printf '%s' "${INSTANCES_RELOAD:-}" | tr ' ' ',')," in *,all,*|*,"$NAME",*) return 0;; esac
  return 1
}

opt_out() {
  if [ ! -f "$M_MANAGED" ]; then say "$NAME: not opted in"; return 0; fi
  if ! probe_loaded; then finish "STOP FAILED: $LC_ERR; unit and markers kept, will retry"; return 0; fi
  if [ "$LOADED" = yes ]; then
    if ! run_lc bootout "$DOMAIN/$LABEL"; then finish "STOP FAILED: launchctl bootout: $(first_line "$TMP/lc.out"); unit and markers kept, will retry"; return 0; fi
  fi
  rm -f "$DST" "$M_MANAGED" "$M_SHA" "$M_SEEDED" "$M_STATUS"
  say "$NAME: opted out: daemon stopped, unit file removed; state, config, tokens, playbooks and logs kept. $PANE_NOTE"
  return 0
}

configure() { # create the instance's config when it has none; returns 0 when config exists afterwards
  case $NAME in
    retro)
      _miss=''
      [ -n "${INSTANCES_RETRO_CHANNEL_ID:-}" ] || _miss="$_miss instances.retro.channelId"
      [ -n "${INSTANCES_RETRO_OP_ITEM:-}" ] || _miss="$_miss instances.retro.opItem"
      if [ -n "$_miss" ]; then finish "NOT READY: no config in $STATE and missing local data:$_miss"; return 1; fi
      [ -f "$REPO/$SETUP" ] || { finish "NOT READY: no config in $STATE and no $REPO/$SETUP to create it"; return 1; }
      with_timeout "$CONFIG_TIMEOUT" env RETRO_CHANNEL_ID="$INSTANCES_RETRO_CHANNEL_ID" RETRO_OP_ITEM="$INSTANCES_RETRO_OP_ITEM" sh "$REPO/$SETUP" >"$TMP/cfg.out" 2>&1; _rc=$?;;
    *)
      [ -f "$REPO/$SETUP" ] || { finish "NOT READY: no config in $STATE and no $REPO/$SETUP to create it"; return 1; }
      with_timeout "$CONFIG_TIMEOUT" env COORDINATOR_STATE_DIR="$STATE" sh "$REPO/$SETUP" >"$TMP/cfg.out" 2>&1; _rc=$?;;
  esac
  case $_rc in
    0) ;;
    3) _why=$(grep -m1 '^NOT-READY:' "$TMP/cfg.out" | cut -c11-210); finish "NOT READY:${_why:- the setup script says it is not ready}"; return 1;;
    *) finish "NOT READY: setup script $SETUP failed (exit $_rc): $(first_line "$TMP/cfg.out")"; return 1;;
  esac
  [ -f "$STATE/config.json" ] || { finish "NOT READY: $SETUP reported success but $STATE/config.json does not exist"; return 1; }
  return 0
}

opt_in() {
  _miss=''
  [ -n "$REPO" ] || _miss="$_miss instances.$NAME.repo"
  if [ -n "$REPO" ] && [ ! -f "$REPO/$MAIN" ]; then _miss="$_miss checkout($REPO/$MAIN)"; fi
  for _t in node herdr op git; do have "$_t" || _miss="$_miss $_t-on-PATH"; done
  [ -f "$SRC" ] || _miss="$_miss unit($SRC; run chezmoi apply)"
  if [ -n "$_miss" ]; then finish "NOT READY: missing$_miss"; return 0; fi

  mkdir -p "$STATE_ROOT" "$LOGDIR" "$STATE" "$AGENTS_DIR" || { finish "NOT READY: cannot create directories"; return 0; }
  if [ ! -f "$M_SEEDED" ]; then
    if [ ! -f "$STATE/config.json" ]; then configure || return 0; fi
    : >"$M_SEEDED"
  fi

  if command -v plutil >/dev/null 2>&1 && ! plutil -lint "$SRC" >"$TMP/lint.out" 2>&1; then
    finish "NOT READY: the unit $SRC is not a valid plist: $(first_line "$TMP/lint.out")"; return 0
  fi
  _before=''; [ -f "$DST" ] && _before=$(sha "$DST")
  _want=$(sha "$SRC")
  if [ "$_before" != "$_want" ]; then
    if ! { cp "$SRC" "$DST.new" && chmod 644 "$DST.new" && mv "$DST.new" "$DST"; }; then finish "NOT READY: cannot write $DST"; return 0; fi
  fi

  if ! probe_loaded; then finish "NOT READY: $LC_ERR"; return 0; fi
  _adopted=no
  if [ "$LOADED" = no ]; then
    if ! run_lc bootstrap "$DOMAIN" "$DST"; then finish "NOT READY: launchctl bootstrap failed: $(first_line "$TMP/lc.out")"; return 0; fi
    if ! probe_loaded || [ "$LOADED" != yes ]; then finish "NOT READY: bootstrap returned 0 but $LABEL is not loaded"; return 0; fi
    : >"$M_MANAGED"; printf '%s\n' "$_want" >"$M_SHA"
    finish "READY (started)"; return 0
  fi
  if [ ! -f "$M_MANAGED" ]; then
    # Adopt a service that is already running: record the file it was loaded from (as it was before this run); touch nothing.
    _adopted=yes; : >"$M_MANAGED"; printf '%s\n' "$_before" >"$M_SHA"
  fi
  _loaded_sha=$(cat "$M_SHA" 2>/dev/null || true)
  if [ "$_loaded_sha" = "$_want" ]; then
    if [ "$_adopted" = yes ]; then finish "READY (adopted: running, not touched)"; else finish "READY (running)"; fi
    return 0
  fi
  if reload_requested; then
    if ! run_lc bootout "$DOMAIN/$LABEL"; then finish "RELOAD FAILED: launchctl bootout: $(first_line "$TMP/lc.out"); the old daemon is still running"; return 0; fi
    if ! run_lc bootstrap "$DOMAIN" "$DST"; then finish "RELOAD FAILED: daemon is stopped, bootstrap failed: $(first_line "$TMP/lc.out"); the next apply will start it"; return 0; fi
    if ! probe_loaded || [ "$LOADED" != yes ]; then finish "RELOAD FAILED: bootstrap returned 0 but $LABEL is not loaded; the next apply will start it"; return 0; fi
    printf '%s\n' "$_want" >"$M_SHA"
    finish "READY (reloaded with the changed unit)"; return 0
  fi
  finish "READY (running); the unit file changed and the daemon was NOT restarted. To reload on purpose: INSTANCES_RELOAD=$NAME chezmoi apply"
  return 0
}

reconcile() {
  load_instance "$1" || return 0
  case $ENABLED in
    true) opt_in;;
    false|'') opt_out;;
    *) say "$NAME: NOT READY: instances.$NAME.enabled must be true or false (found '$ENABLED'); nothing done";;
  esac
  return 0
}

for _n in ${INSTANCES_LIST:-coordinator retro}; do reconcile "$_n"; done
exit 0
