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
# Instances: coordinator and retro (personal profile), coordinator-work (axon-work-computer profile: the Matrix coordinator; its flag is still
# data.instances.coordinator.enabled, the profile picks the variant; the wrapper only exports the variants of its own profile).
# Markers: $INSTANCES_STATE_ROOT (default ~/.local/state/instances)/<name>.{managed,unit-sha,configuring,status}.
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
# The ring producer (agent-alert) is deployed here but is not on PATH; the work setup script requires it on PATH (for its own run only).
AGENT_ALERT_DIR=$HOME_DIR/.local/share/agent-alert/core
DOMAIN="gui/$(id -u)"
TMP=$(mktemp -d "${TMPDIR:-/tmp}/instances.XXXXXX") || exit 0
trap 'rm -rf "$TMP"' EXIT

say() { printf '[instances] %s\n' "$*"; }

with_timeout() { # with_timeout SECONDS CMD ARGS...
  _secs=$1; shift
  # The command runs in its own process group, and on timeout the whole group is killed (a setup script's children included). Exit 124.
  if command -v perl >/dev/null 2>&1; then
    perl -e 'my $t = shift; my $pid = fork(); defined $pid or exit 127;
      if (!$pid) { setpgrp(0, 0); exec @ARGV; exit 127 }
      setpgrp($pid, $pid);
      my $stop = sub { my $code = shift; kill "TERM", -$pid; select(undef, undef, undef, 1); kill "KILL", -$pid; waitpid($pid, 0); exit $code };
      $SIG{ALRM} = sub { $stop->(124) };
      $SIG{INT} = sub { $stop->(130) }; $SIG{TERM} = sub { $stop->(143) }; $SIG{HUP} = sub { $stop->(129) };
      alarm $t; waitpid($pid, 0); my $s = $?; exit(($s & 127) ? 128 + ($s & 127) : $s >> 8)' "$_secs" "$@"
  else "$@"; fi
  _r=$?
  # Ctrl-C, TERM or HUP reached the command (and the wrapper cleaned up its group): the apply is cancelled, not "that step failed".
  case $_r in 129|130|143) say "cancelled (signal); stopping"; exit "$_r";; esac
  return "$_r"
}
first_line() { head -n 1 "$1" 2>/dev/null | cut -c1-200; }
sha() { shasum -a 256 "$1" 2>/dev/null | cut -d' ' -f1; }
have() { # have TOOL: found on the daemon's PATH (the unit's PATH: per-instance extra directories first)
  _old=$IFS; IFS=:
  for _d in $ITP; do if [ -x "$_d/$1" ]; then IFS=$_old; return 0; fi; done
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
      MAIN=src/coordinatord/main.ts; SETUP=scripts/instance-setup.sh; CFGNAME=coordinator; EXTRA_PATH=''; CFG_TO=${INSTANCES_CONFIG_TIMEOUT:-120}
      ENABLED=${INSTANCES_COORDINATOR_ENABLED:-}; REPO=${INSTANCES_COORDINATOR_REPO:-};;
    coordinator-work)
      # The work Matrix coordinator: the paths are the ones the coordinator's own setup script and docs/launchd/local.coordinatord.work.plist use.
      # Its setup also needs op, a signed-in Pi, the homeserver and a model call, so it gets a long timeout.
      LABEL=local.coordinatord.work; LOGDIR=$HOME_DIR/Library/Logs/coordinator-work; STATE=$HOME_DIR/.local/share/coordinator-work
      MAIN=src/coordinatord/main.ts; SETUP=scripts/work-instance-setup.sh; CFGNAME=coordinator; CFG_TO=${INSTANCES_CONFIG_TIMEOUT:-900}
      ENABLED=${INSTANCES_COORDINATOR_WORK_ENABLED:-}; REPO=${INSTANCES_COORDINATOR_WORK_REPO:-}; EXTRA_PATH=${INSTANCES_COORDINATOR_WORK_EXTRA_PATH:-};;
    retro)
      LABEL=local.retrod; LOGDIR=$HOME_DIR/Library/Logs/retro; STATE=$HOME_DIR/.local/share/retro
      MAIN=src/retrod/main.ts; SETUP=scripts/configure.sh; CFGNAME=retro; EXTRA_PATH=''; CFG_TO=${INSTANCES_CONFIG_TIMEOUT:-120}
      ENABLED=${INSTANCES_RETRO_ENABLED:-}; REPO=${INSTANCES_RETRO_REPO:-};;
    *) say "unknown instance $1"; return 1;;
  esac
  ITP=$TOOL_PATH; [ -z "$EXTRA_PATH" ] || ITP=$EXTRA_PATH:$TOOL_PATH
  SRC=$UNIT_DIR/$LABEL.plist; DST=$AGENTS_DIR/$LABEL.plist
  M_MANAGED=$STATE_ROOT/$NAME.managed; M_SHA=$STATE_ROOT/$NAME.unit-sha; M_CONFIGURING=$STATE_ROOT/$NAME.configuring; M_STATUS=$STATE_ROOT/$NAME.status
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
  # Ownership goes last: if the unit cannot be removed, the next apply must still know it is ours to remove.
  rm -f "$DST" 2>/dev/null
  if [ -e "$DST" ] || [ -L "$DST" ]; then finish "STOP FAILED: cannot remove $DST (daemon is stopped); markers kept, will retry"; return 0; fi
  rm -f "$M_MANAGED" "$M_SHA" "$M_STATUS"
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
      with_timeout "$CFG_TO" env PATH="$ITP:$PATH" RETRO_CHANNEL_ID="$INSTANCES_RETRO_CHANNEL_ID" RETRO_OP_ITEM="$INSTANCES_RETRO_OP_ITEM" sh "$REPO/$SETUP" >"$TMP/cfg.out" 2>&1 </dev/null; _rc=$?;;
    coordinator-work)
      # The coordinator repo's setup script. Dotfiles owns the unit and the start, so it is asked for the config half only (--config-only;
      # until the coordinator repo has that flag the script rejects it and the instance stays NOT READY with that reason). The checkout the
      # owner cloned by hand is the commit it is asked to accept (--rev HEAD): that checks the tree is clean, not that the commit is reviewed.
      [ -f "$REPO/$SETUP" ] || { finish "NOT READY: no config in $STATE and no $REPO/$SETUP to create it"; return 1; }
      _rev=$(env PATH="$ITP:$PATH" git -C "$REPO" rev-parse HEAD 2>/dev/null) || { finish "NOT READY: $REPO is not a git checkout (cannot read its commit)"; return 1; }
      with_timeout "$CFG_TO" env PATH="$ITP:$AGENT_ALERT_DIR:$PATH" bash "$REPO/$SETUP" --yes-this-is-the-work-computer --config-only --rev "$_rev" --state-dir "$STATE" >"$TMP/cfg.out" 2>&1 </dev/null; _rc=$?;;
    *)
      [ -f "$REPO/$SETUP" ] || { finish "NOT READY: no config in $STATE and no $REPO/$SETUP to create it"; return 1; }
      with_timeout "$CFG_TO" env PATH="$ITP:$PATH" COORDINATOR_STATE_DIR="$STATE" sh "$REPO/$SETUP" >"$TMP/cfg.out" 2>&1 </dev/null; _rc=$?;;
  esac
  case $_rc in
    0) ;;
    3) _why=$(grep -m1 '^NOT-READY:' "$TMP/cfg.out" | cut -c11-210); finish "NOT READY:${_why:- the setup script says it is not ready}"; return 1;;
    *) # A script that narrates (the work one prints [ok] lines first) puts the reason on a [FAIL] line; otherwise the first line says it.
       _why=$(grep -m1 '^\[FAIL\]' "$TMP/cfg.out" | cut -c9-210); [ -n "$_why" ] || _why=$(first_line "$TMP/cfg.out")
       finish "NOT READY: setup script $SETUP failed (exit $_rc): $_why"; return 1;;
  esac
  [ -f "$STATE/config.json" ] || { finish "NOT READY: $SETUP reported success but $STATE/config.json does not exist"; return 1; }
  return 0
}

opt_in() {
  _miss=''
  [ -n "$REPO" ] || _miss="$_miss instances.$CFGNAME.repo"
  if [ -n "$REPO" ] && [ ! -f "$REPO/$MAIN" ]; then _miss="$_miss checkout($REPO/$MAIN)"; fi
  for _t in node herdr op git; do have "$_t" || _miss="$_miss $_t-on-PATH"; done
  [ -f "$SRC" ] || _miss="$_miss unit($SRC; run chezmoi apply)"
  if [ -n "$_miss" ]; then finish "NOT READY: missing$_miss"; return 0; fi

  mkdir -p "$STATE_ROOT" "$LOGDIR" "$STATE" "$AGENTS_DIR" || { finish "NOT READY: cannot create directories"; return 0; }
  # A config that exists is the owner's (or an earlier setup run's that finished). One left by a setup run of ours that did not finish
  # is not: the marker makes the next apply run the setup again instead of trusting half a config.
  if [ -e "$M_CONFIGURING" ] || [ -L "$M_CONFIGURING" ] || [ ! -f "$STATE/config.json" ]; then
    if ! { touch "$M_CONFIGURING" && [ -f "$M_CONFIGURING" ]; }; then finish "NOT READY: cannot write $M_CONFIGURING"; return 0; fi
    configure || return 0
    rm -f "$M_CONFIGURING"
  fi

  if command -v plutil >/dev/null 2>&1 && ! plutil -lint "$SRC" >"$TMP/lint.out" 2>&1; then
    finish "NOT READY: the unit $SRC is not a valid plist: $(first_line "$TMP/lint.out")"; return 0
  fi
  # Ask launchd first, then record ownership, and only then change anything on disk or in launchd.
  if ! probe_loaded; then finish "NOT READY: $LC_ERR"; return 0; fi
  _before=''; [ -f "$DST" ] && _before=$(sha "$DST")
  _want=$(sha "$SRC")
  _adopted=no
  if [ ! -f "$M_MANAGED" ]; then
    if [ "$LOADED" = yes ]; then _adopted=yes; _own=$_before   # running already: record the file it was loaded from, as it is right now
    else _own=$_want; fi                                         # about to be started by us
    if ! { printf '%s\n' "$_own" >"$M_SHA" && touch "$M_MANAGED" && [ -f "$M_MANAGED" ]; }; then finish "NOT READY: cannot record ownership in $STATE_ROOT"; return 0; fi
  fi
  if [ "$_before" != "$_want" ]; then
    if ! { cp "$SRC" "$DST.new" && chmod 644 "$DST.new" && mv "$DST.new" "$DST"; }; then finish "NOT READY: cannot write $DST"; return 0; fi
  fi
  if [ "$LOADED" = no ]; then
    if ! printf '%s\n' "$_want" >"$M_SHA"; then finish "NOT READY: cannot record ownership in $STATE_ROOT"; return 0; fi
    if ! run_lc bootstrap "$DOMAIN" "$DST"; then finish "NOT READY: launchctl bootstrap failed: $(first_line "$TMP/lc.out")"; return 0; fi
    if ! probe_loaded || [ "$LOADED" != yes ]; then finish "NOT READY: bootstrap returned 0 but $LABEL could not be confirmed loaded"; return 0; fi
    finish "READY (started)"; return 0
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
    printf '%s\n' "$_want" >"$M_SHA" || say "$NAME: WARN: cannot record the reloaded unit in $M_SHA; it will be reported as changed"
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
    *) say "$NAME: NOT READY: instances.$CFGNAME.enabled must be true or false (found '$ENABLED'); nothing done";;
  esac
  return 0
}

for _n in ${INSTANCES_LIST:-coordinator retro}; do reconcile "$_n"; done
exit 0
