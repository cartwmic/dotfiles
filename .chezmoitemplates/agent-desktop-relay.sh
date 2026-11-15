#!/bin/sh
# agent-desktop-relay: the kitty helper for agent-desktop on a Mac. Source: .chezmoitemplates/agent-desktop-relay.sh. Chezmoi never
# deploys this file on its own: the install step run_onchange_after_66_agent_desktop_macos.sh.tmpl copies it to
# ~/.local/bin/agent-desktop-relay (personal profile only). Contract, permissions and how to reproduce: docs/agent-desktop.md.
#
# Why. macOS gives Screen Recording and Accessibility to the app that started the process. A plain ssh shell has neither, and kitty
# already has both. So the helper runs inside kitty, takes one agent-desktop call at a time, runs the macOS script with it and hands
# back stdout, stderr and the exit code byte for byte. `agent-desktop` over ssh sends its call here before it touches the screen.
#
#   agent-desktop-relay serve         the loop. Started inside kitty by `start`; a second one refuses to start
#   agent-desktop-relay start         open kitty with `serve` unless the helper is already running; wait until it is up, then hide
#                                     that kitty (NSRunningApplication hide: no Automation permission; a failure only goes to the log)
#   agent-desktop-relay stop          end the helper (it finishes the call it is on first); the next `start` brings it back
#   agent-desktop-relay status        "running (pid N)" and exit 0, or "not running" and exit 1
#   agent-desktop-relay call ARGS...  send one call to the helper and print its answer; `agent-desktop` runs this over ssh
#
# How a call travels. The caller makes a folder under STATE/relay/req/ holding the working directory and one file per argument (the
# bytes as given, so quotes, newlines and empty arguments arrive unchanged), then writes the folder's name as one line to the FIFO
# STATE/relay/requests. The helper reads names one at a time, runs `~/.local/bin/agent-desktop ARGS` in that directory with
# AGENT_DESKTOP_IN_RELAY=1 and AGENT_DESKTOP_RUN_ID=<the folder name>, and puts out, err and rc in the folder. The caller waits for
# rc, prints out and err, removes the folder and exits with rc. Because the helper takes one name at a time, calls never mix.
# The wait ends on a fact: the answer is there, or the helper is gone (exit 1).
#
# Override for tests: AGENT_DESKTOP_BIN (the script the helper runs), AGENT_DESKTOP_RELAY_START_WAIT (seconds `start` waits, 10),
# KITTY_APP (/Applications/kitty.app).
# Exit: 0 ok; 1 the helper is not running or went away, or `start` could not bring it up; 2 usage.
# Log: ${XDG_STATE_HOME:-~/.local/state}/agent-desktop/agent-desktop.log, the same file and shape as agent-desktop: one line per
# forwarded call (its run id, which the steps inside the helper share) and one when the helper starts or stops.
set -u

NAME="agent-desktop-relay"
DOC="docs/agent-desktop.md"
state="${XDG_STATE_HOME:-$HOME/.local/state}/agent-desktop"
spool="$state/relay"
pidf="$spool/pid"
fifo="$spool/requests"
LOG="$state/agent-desktop.log"
SELF=$0
case $SELF in /*) ;; *) SELF="$PWD/$SELF" ;; esac
RUN_ID="relay-$$"
START=$(date +%s)

fail() {  # fail CODE MESSAGE...
  code=$1
  shift
  echo "[$NAME] ERROR: $*" >&2
  exit "$code"
}

record() {  # record TEXT: one line in the log
  printf '%s run=%s elapsed=%ss %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$RUN_ID" "$(($(date +%s) - START))" "$*" >>"$LOG"
}

alive() {  # alive: 0 when the pid file names a live helper process (it may not have its FIFO yet). Sets HELPER_PID.
  HELPER_PID=$(cat "$pidf" 2>/dev/null) || return 1
  case $HELPER_PID in ''|*[!0-9]*) return 1 ;; esac
  kill -0 "$HELPER_PID" 2>/dev/null || return 1
  case $(ps -p "$HELPER_PID" -o command= 2>/dev/null) in *"$NAME"*) return 0 ;; esac  # the pid may be some other program's now
  return 1
}

running() {  # running: 0 when the helper is alive and has its FIFO, so a call can be sent
  alive && [ -p "$fifo" ]
}

claim() {  # claim: write our pid to the pid file unless a live helper has it. 0 if we hold it.
  n=0
  while [ "$n" -lt 2 ]; do
    printf '%s\n' "$$" >"$pidf.$$"
    if ln "$pidf.$$" "$pidf" 2>/dev/null; then
      rm -f "$pidf.$$"
      return 0
    fi
    rm -f "$pidf.$$"
    if alive; then return 1; fi  # a helper that is still setting up counts: it has the pid file before its FIFO
    rm -f "$pidf"  # left by a helper that died
    n=$((n + 1))
  done
  return 1
}

leave() {  # leave: the helper's exit: remove what it made, if it is still ours
  if [ "$(cat "$pidf" 2>/dev/null)" = "$$" ]; then
    rm -f "$pidf" "$fifo"
    record "relay stop pid=$$"
  fi
}

serve_one() {  # serve_one ID: run one request and write its answer into its folder
  rid=$1
  d="$spool/req/$rid"
  [ -d "$d" ] || return 0  # the caller gave up
  n=$(cat "$d/argc" 2>/dev/null) || return 0
  set --
  i=0
  while [ "$i" -lt "$n" ]; do
    v=$(cat "$d/a$i"; printf x)  # the x keeps trailing newlines from being stripped
    set -- "$@" "${v%x}"
    i=$((i + 1))
  done
  cwd=$(cat "$d/cwd"; printf x)
  cwd=${cwd%x}
  rc=0
  (
    cd "$cwd" 2>/dev/null || { echo "[$NAME] ERROR: cannot enter $cwd" >&2; exit 1; }
    AGENT_DESKTOP_IN_RELAY=1
    AGENT_DESKTOP_RUN_ID=$rid
    export AGENT_DESKTOP_IN_RELAY AGENT_DESKTOP_RUN_ID
    exec "${AGENT_DESKTOP_BIN:-$HOME/.local/bin/agent-desktop}" "$@"
  ) </dev/null >"$d/out" 2>"$d/err" || rc=$?
  printf '%s' "$rc" >"$d/rc.tmp" && mv "$d/rc.tmp" "$d/rc"
}

cmd_serve() {
  mkdir -p "$spool/req"
  claim || fail 1 "already running (pid $(cat "$pidf" 2>/dev/null)); only one helper runs at a time"
  trap leave EXIT
  trap 'exit 0' INT TERM HUP
  rm -rf "$spool/req" "$fifo"  # calls left by an earlier helper are not run late
  mkdir -p "$spool/req"
  mkfifo "$fifo"
  exec 3<>"$fifo"  # open for read and write, so the FIFO never reports end of input when a caller closes it
  record "relay start pid=$$"
  while read -r id <&3; do
    serve_one "$id"
  done
}

# The JavaScript that hides an app by process id. NSRunningApplication needs no permission and sends no Apple event, so it never
# raises the Automation prompt. No single quote may appear in it.
HIDE_JXA='
ObjC.import("AppKit");
function spin(s) { $.NSRunLoop.currentRunLoop.runUntilDate($.NSDate.dateWithTimeIntervalSinceNow(s)); }
function run(argv) {
  var app = $.NSRunningApplication.runningApplicationWithProcessIdentifier(parseInt(argv[0], 10));
  // In JavaScript for Automation a method with no arguments runs when it is read (app.hide, not app.hide()). It answers false even
  // when it works, and macOS acts on it only while the run loop turns, so spin the loop and read the state back.
  var asked = app.hide;
  for (var i = 0; i < 20 && !app.hidden; i++) { spin(0.1); }
  if (!app.hidden) { throw new Error("the app is still not hidden after 2 s"); }
  return "hidden";
}
'

hide_window() {  # hide_window: hide the kitty that runs the helper, once, after start. A failure is logged and does not fail start.
  kpid=$(ps -p "$HELPER_PID" -o ppid= 2>/dev/null | tr -d ' ')
  case $kpid in ''|*[!0-9]*) return 0 ;; esac
  case $(ps -p "$kpid" -o command= 2>/dev/null) in *kitty*) ;; *) return 0 ;; esac  # only a kitty is ever hidden
  if err=$(osascript -l JavaScript -e "$HIDE_JXA" "$kpid" 2>&1); then
    record "relay hid kitty pid=$kpid"
  else
    record "relay could not hide kitty pid=$kpid: $(printf '%s' "$err" | tr '\n' ' ')"
  fi
}

cmd_start() {
  if running; then
    echo "[$NAME] already running (pid $HELPER_PID)"
    return 0
  fi
  mkdir -p "$spool"
  # kitty 0.37 on macOS ignores --start-as=minimized, so hide_window hides it once the helper is up (docs/agent-desktop.md).
  open -na "${KITTY_APP:-/Applications/kitty.app}" --args --start-as=minimized --title=agent-desktop-relay \
    --override=macos_quit_when_last_window_closed=yes /bin/sh "$SELF" serve || fail 1 "could not open kitty (is it installed, and is someone logged in at the Mac?). Steps: $DOC"
  waited=0
  limit=$(( ${AGENT_DESKTOP_RELAY_START_WAIT:-10} * 10 ))
  until running; do
    if [ "$waited" -ge "$limit" ]; then
      fail 1 "kitty was opened but the helper did not come up. Is the Mac's screen logged in? Steps: $DOC"
    fi
    sleep 0.1
    waited=$((waited + 1))
  done
  hide_window
  echo "[$NAME] started (pid $HELPER_PID)"
}

cmd_stop() {
  if ! running; then
    echo "[$NAME] not running"
    return 0
  fi
  kill "$HELPER_PID" 2>/dev/null
  waited=0
  while kill -0 "$HELPER_PID" 2>/dev/null; do
    if [ "$waited" -ge 100 ]; then fail 1 "the helper (pid $HELPER_PID) is still on its call after 10 s; try: kill -9 $HELPER_PID"; fi
    sleep 0.1
    waited=$((waited + 1))
  done
  echo "[$NAME] stopped"
}

cmd_status() {
  if running; then
    echo "running (pid $HELPER_PID)"
  else
    echo "not running"
    return 1
  fi
}

cmd_call() {
  mkdir -p "$state"
  if ! running; then
    RUN_ID="relay-$$"
    record "FAIL relay call (helper not running)"
    echo "[agent-desktop] ERROR: the kitty helper ($NAME) is not running, so this call has no screen permissions. Start it with: $NAME start (check with: $NAME status). Steps: $DOC" >&2
    exit 1
  fi
  mkdir -p "$spool/req"
  d=$(mktemp -d "$spool/req/r.XXXXXX") || fail 1 "cannot make a request folder under $spool/req"
  RUN_ID=${d##*/}
  trap 'rm -rf "$d"' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  n=0
  for a in "$@"; do
    printf '%s' "$a" >"$d/a$n"
    n=$((n + 1))
  done
  printf '%s' "$PWD" >"$d/cwd"
  printf '%s' "$n" >"$d/argc"
  printf '%s\n' "$RUN_ID" 1<>"$fifo"  # read-write open: does not block if the helper has just gone
  while [ ! -f "$d/rc" ]; do
    if ! kill -0 "$HELPER_PID" 2>/dev/null; then
      record "FAIL relay call (helper went away)"
      echo "[agent-desktop] ERROR: the kitty helper ($NAME) stopped while it had your call, so the call may not have run. Start it with: $NAME start. Steps: $DOC" >&2
      exit 1
    fi
    sleep 0.02
  done
  cat "$d/out"
  cat "$d/err" >&2
  rc=$(cat "$d/rc")
  case $rc in ''|*[!0-9]*) rc=1 ;; esac
  record "relay call args=$# exit=$rc"
  exit "$rc"
}

[ $# -ge 1 ] || { echo "usage: $NAME serve | start | stop | status | call ARGS..." >&2; exit 2; }
cmd=$1
shift
case $cmd in
  serve) cmd_serve ;;
  start) cmd_start ;;
  stop) cmd_stop ;;
  status) cmd_status ;;
  call) cmd_call "$@" ;;
  *) echo "usage: $NAME serve | start | stop | status | call ARGS..." >&2; exit 2 ;;
esac
