#!/bin/sh
# instances_reconcile_systemd.sh: Linux twin of instances_reconcile.sh. Makes each instance (coordinator) match its opt-in flag with a
# systemd user unit where macOS uses a LaunchAgent. Run by chezmoi on every apply (run_after_75_instances_reconcile.sh.tmpl on Linux); it
# can also be run by hand with the same environment. Personal profile only (the work coordinator is macOS).
#
# Desired state comes from the local chezmoi.yaml (data.instances.<name>.enabled), passed in as INSTANCES_COORDINATOR_ENABLED.
#   true            opt in: dirs, config (once), the unit file, and start (enable --now). Everything is idempotent.
#   false or unset  opt out, but only for an instance this script started or adopted (marker). A machine that never opted in is left alone.
#
# The safety rules, in force on every run (the same as the launchd script's, with systemctl --user for launchctl):
#   * systemctl is called for exactly: show-environment and is-active (read-only), daemon-reload (after the unit file changed),
#     enable --now (the instance is not running), enable (once, when a running service is adopted: it must also start at boot; it
#     does not touch the running process), restart (a requested reload of a changed unit) and disable --now (opt out).
#     A running service is never restarted because a template re-rendered.
#   * A unit file that differs from the one the service was started with is REPORTED (reload needed). It is restarted only when
#     INSTANCES_RELOAD names the instance (or "all") on that run, and only if the unit really changed.
#   * Opt-out never deletes state, config, tokens, playbooks or logs. It removes the unit file and the markers.
#   * Every outcome is one status line and exit 0, so a missing checkout or user manager cannot block other chezmoi work. The next run starts over.
#   * Nothing secret is read, printed or stored here. The repo's own setup script owns tokens.
#
# Markers: $INSTANCES_STATE_ROOT (default ~/.local/state/instances)/<name>.{managed,unit-sha,configuring,status}, as on macOS.
# Logs: the journal (journalctl --user -u coordinatord), where the macOS units write ~/Library/Logs/<name>/*.log.
# Test hooks: INSTANCES_STATE_ROOT, INSTANCES_UNIT_DIR (the unit source), INSTANCES_SYSTEMD_DIR (where the unit is installed), INSTANCES_TOOL_PATH, INSTANCES_TIMEOUT.
set -u

PANE_NOTE='the Pi pane keeps running (stopping the daemon does not close it); close it yourself if you want it gone'

HOME_DIR=${HOME:-}
[ -n "$HOME_DIR" ] && [ -d "$HOME_DIR" ] || { echo "[instances] WARN: HOME is not a directory; nothing done" >&2; exit 0; }
STATE_ROOT=${INSTANCES_STATE_ROOT:-$HOME_DIR/.local/state/instances}
UNIT_DIR=${INSTANCES_UNIT_DIR:-$HOME_DIR/.local/share/instances/systemd}
SYSTEMD_DIR=${INSTANCES_SYSTEMD_DIR:-$HOME_DIR/.config/systemd/user}
# The PATH the unit gives the daemon (ITP, set per instance); the tools it needs must be found on it, not on whatever PATH this script has.
COORDINATOR_ITP=${INSTANCES_TOOL_PATH:-$HOME_DIR/.local/share/mise/shims:$HOME_DIR/.local/bin:$HOME_DIR/.t3/bin:/usr/local/bin:/usr/bin:/bin}
TIMEOUT=${INSTANCES_TIMEOUT:-30}
CFG_TO=${INSTANCES_CONFIG_TIMEOUT:-120}

select_instance() { # select_instance coordinator: sets the per-instance variables the functions below read
  NAME=$1
  case $1 in
    coordinator)
      UNIT=coordinatord.service; STATE=$HOME_DIR/.local/share/coordinator; MAIN=src/coordinatord/main.ts; SETUP=scripts/instance-setup.sh
      ENABLED=${INSTANCES_COORDINATOR_ENABLED:-}; REPO=${INSTANCES_COORDINATOR_REPO:-}; ITP=$COORDINATOR_ITP;;
  esac
  SRC=$UNIT_DIR/$UNIT
  DST=$SYSTEMD_DIR/$UNIT
  M_MANAGED=$STATE_ROOT/$NAME.managed; M_SHA=$STATE_ROOT/$NAME.unit-sha; M_CONFIGURING=$STATE_ROOT/$NAME.configuring; M_STATUS=$STATE_ROOT/$NAME.status
}

TMP=$(mktemp -d "${TMPDIR:-/tmp}/instances.XXXXXX") || exit 0
trap 'rm -rf "$TMP"' EXIT

say() { printf '[instances] %s\n' "$*"; }
first_line() { head -n 1 "$1" 2>/dev/null | cut -c1-200; }
sha() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" 2>/dev/null; else shasum -a 256 "$1" 2>/dev/null; fi | cut -d' ' -f1; }
have() { # have TOOL: found on the daemon's PATH
  _old=$IFS; IFS=:
  for _d in $ITP; do if [ -x "$_d/$1" ]; then IFS=$_old; return 0; fi; done
  IFS=$_old; return 1
}
# systemctl, by name (so a test can put a stub first on PATH). OUT is its combined output.
run_sc() { timeout "$TIMEOUT" systemctl --user "$@" >"$TMP/sc.out" 2>&1; }
probe_active() { # sets ACTIVE=yes|no; returns 1 if there is no user manager to ask
  if ! run_sc show-environment; then SC_ERR="no systemd user manager: $(first_line "$TMP/sc.out")"; return 1; fi
  if run_sc is-active --quiet "$UNIT"; then ACTIVE=yes; else ACTIVE=no; fi
  return 0
}
finish() { # finish MESSAGE: the one status line of this instance
  say "$NAME: $1"
  mkdir -p "$STATE_ROOT" 2>/dev/null && printf '%s\n' "$1" >"$M_STATUS" 2>/dev/null
  return 0
}
reload_requested() { case ",$(printf '%s' "${INSTANCES_RELOAD:-}" | tr ' ' ',')," in *,all,*|*,"$NAME",*) return 0;; esac; return 1; }

opt_out() {
  if [ ! -f "$M_MANAGED" ]; then say "$NAME: not opted in"; return 0; fi
  if ! probe_active; then finish "STOP FAILED: $SC_ERR; unit and markers kept, will retry"; return 0; fi
  if ! run_sc disable --now "$UNIT"; then finish "STOP FAILED: systemctl disable --now: $(first_line "$TMP/sc.out"); unit and markers kept, will retry"; return 0; fi
  # Ownership goes last: if the unit cannot be removed, the next apply must still know it is ours to remove.
  rm -f "$DST" 2>/dev/null
  if [ -e "$DST" ] || [ -L "$DST" ]; then finish "STOP FAILED: cannot remove $DST (daemon is stopped); markers kept, will retry"; return 0; fi
  run_sc daemon-reload || true
  rm -f "$M_MANAGED" "$M_SHA" "$M_STATUS"
  say "$NAME: opted out: daemon stopped, unit file removed; state, config, tokens, playbooks and logs kept. $PANE_NOTE"
  return 0
}

configure() { # create the instance's config when it has none; returns 0 when config exists afterwards
  [ -f "$REPO/$SETUP" ] || { finish "NOT READY: no config in $STATE and no $REPO/$SETUP to create it"; return 1; }
  timeout "$CFG_TO" env PATH="$ITP:$PATH" COORDINATOR_STATE_DIR="$STATE" sh "$REPO/$SETUP" >"$TMP/cfg.out" 2>&1 </dev/null; _rc=$?
  case $_rc in
    0) ;;
    3) _why=$(grep -m1 '^NOT-READY:' "$TMP/cfg.out" | cut -c11-210); finish "NOT READY:${_why:- the setup script says it is not ready}"; return 1;;
    *) _why=$(grep -m1 '^\[FAIL\]' "$TMP/cfg.out" | cut -c9-210); [ -n "$_why" ] || _why=$(first_line "$TMP/cfg.out")
       finish "NOT READY: setup script $SETUP failed (exit $_rc): $_why"; return 1;;
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

  mkdir -p "$STATE_ROOT" "$STATE" "$SYSTEMD_DIR" || { finish "NOT READY: cannot create directories"; return 0; }
  # A config that exists is the owner's (or an earlier setup run's that finished). One left by a setup run of ours that did not finish
  # is not: the marker makes the next apply run the setup again instead of trusting half a config.
  if [ -e "$M_CONFIGURING" ] || [ -L "$M_CONFIGURING" ] || [ ! -f "$STATE/config.json" ]; then
    if ! { touch "$M_CONFIGURING" && [ -f "$M_CONFIGURING" ]; }; then finish "NOT READY: cannot write $M_CONFIGURING"; return 0; fi
    configure || return 0
    rm -f "$M_CONFIGURING"
  fi

  # Ask systemd first, then record ownership, and only then change anything on disk or in systemd.
  if ! probe_active; then finish "NOT READY: $SC_ERR"; return 0; fi
  _before=''; [ -f "$DST" ] && _before=$(sha "$DST")
  _want=$(sha "$SRC")
  _adopted=no
  if [ ! -f "$M_MANAGED" ]; then
    if [ "$ACTIVE" = yes ]; then _adopted=yes; _own=$_before   # running already: record the file it was started from, as it is right now
    else _own=$_want; fi                                        # about to be started by us
    if ! { printf '%s\n' "$_own" >"$M_SHA" && touch "$M_MANAGED" && [ -f "$M_MANAGED" ]; }; then finish "NOT READY: cannot record ownership in $STATE_ROOT"; return 0; fi
    # An adopted hand-made unit may be running but not enabled: enable (no --now) makes it start at boot and leaves the process alone.
    if [ "$_adopted" = yes ] && ! run_sc enable "$UNIT"; then say "$NAME: WARN: systemctl enable failed: $(first_line "$TMP/sc.out"); it runs now but may not start at boot"; fi
  fi
  if [ "$_before" != "$_want" ]; then
    if ! { cp "$SRC" "$DST.new" && chmod 644 "$DST.new" && mv "$DST.new" "$DST"; }; then finish "NOT READY: cannot write $DST"; return 0; fi
    run_sc daemon-reload || { finish "NOT READY: systemctl daemon-reload failed: $(first_line "$TMP/sc.out")"; return 0; }
  fi
  if [ "$ACTIVE" = no ]; then
    if ! printf '%s\n' "$_want" >"$M_SHA"; then finish "NOT READY: cannot record ownership in $STATE_ROOT"; return 0; fi
    if ! run_sc enable --now "$UNIT"; then finish "NOT READY: systemctl enable --now failed: $(first_line "$TMP/sc.out")"; return 0; fi
    if ! probe_active || [ "$ACTIVE" != yes ]; then finish "NOT READY: enable --now returned 0 but $UNIT is not active"; return 0; fi
    finish "READY (started)"; return 0
  fi
  _loaded_sha=$(cat "$M_SHA" 2>/dev/null || true)
  if [ "$_loaded_sha" = "$_want" ]; then
    if [ "$_adopted" = yes ]; then finish "READY (adopted: running, not touched)"; else finish "READY (running)"; fi
    return 0
  fi
  if reload_requested; then
    if ! run_sc restart "$UNIT"; then finish "RELOAD FAILED: systemctl restart: $(first_line "$TMP/sc.out"); the next apply will start it"; return 0; fi
    if ! probe_active || [ "$ACTIVE" != yes ]; then finish "RELOAD FAILED: restart returned 0 but $UNIT is not active; the next apply will start it"; return 0; fi
    printf '%s\n' "$_want" >"$M_SHA" || say "$NAME: WARN: cannot record the reloaded unit in $M_SHA; it will be reported as changed"
    finish "READY (reloaded with the changed unit)"; return 0
  fi
  finish "READY (running); the unit file changed and the daemon was NOT restarted. To reload on purpose: INSTANCES_RELOAD=$NAME chezmoi apply"
  return 0
}

for _n in coordinator; do
  select_instance "$_n"
  case $ENABLED in
    true) opt_in;;
    false|'') opt_out;;
    *) say "$NAME: NOT READY: instances.$NAME.enabled must be true or false (found '$ENABLED'); nothing done";;
  esac
done
exit 0
