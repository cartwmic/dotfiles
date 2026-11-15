#!/bin/sh
# agent-desktop for macOS: screenshot, list windows, focus, move and click the pointer, type and press keys, report the pointer,
# and `ui` (Vercel's agent-desktop: list and click an app's controls by name). Agents call it; Michael can run it too.
# Source: .chezmoitemplates/agent-desktop-macos.sh. Chezmoi never deploys this file on its own: the install step
# run_onchange_after_66_agent_desktop_macos.sh.tmpl copies it to ~/.local/bin/agent-desktop on a Mac (both profiles).
# Contract, permissions and how to reproduce: docs/agent-desktop.md.
#
#   agent-desktop shot FILE [REGION]                screenshot to FILE; REGION is one argument, "X,Y WxH"; prints FILE
#   agent-desktop windows                           tab-separated header line, then one line per window: app, title, at, size, pid
#   agent-desktop focus NAME                        bring the app named NAME (the first column of `windows`) to the front
#   agent-desktop move X Y                          move the pointer to X,Y
#   agent-desktop click X Y [left|right|middle]     move, then click (default left)
#   agent-desktop type TEXT                         type TEXT
#   agent-desktop key KEY [MOD...]                  press KEY with modifiers held: key comma ctrl
#   agent-desktop cursor                            print the pointer position as "X Y"
#   agent-desktop ui ARGS...                        run Vercel's agent-desktop with ARGS; its output and exit code come back unchanged
#
# Built on what macOS ships: `screencapture` for shot, and `osascript` running JavaScript for Automation (JXA) for the rest: Core
# Graphics for the window list, the pointer and clicks, System Events for focus, typing and keys. Every osascript call is
#   osascript -l JavaScript -e "$JXA" ACTION [ARG...]
# so the arguments reach the JavaScript as data and are never put into code. Vercel's program is started only by `ui`.
#
# Permissions. An ssh session runs under /usr/libexec/sshd-keygen-wrapper, and that program needs Screen Recording (shot, windows)
# and Accessibility (focus, move, click, type, key). macOS drops posted input and blanks window titles silently when they are
# missing, so those actions first ask the system whether the grant is there (CGPreflightScreenCaptureAccess, AXIsProcessTrusted;
# neither raises a prompt) and exit 1 with a message that names the permission and docs/agent-desktop.md. `cursor` needs neither.
#
# `key` looks the key name up in a table of macOS key codes and sends the code to System Events with the modifiers held ("using
# command down"). It does not post a key event with modifier flags set. Vercel's trial lost a cmd+a now and then; the cause was not
# found there, so the live proof (docs/agent-desktop.md) repeats key a cmd and reports it.
#
# Coordinates are what macOS uses for the pointer: points of the global display space. A Retina screenshot is larger than that in
# pixels (twice, on a 2x display), so divide screenshot pixels by the scale before clicking on something seen in a shot.
#
# Exit: 0 ok; 1 a tool failed or a permission is missing; 2 usage; 69 a needed tool is missing (or, for `ui`, Vercel's program).
# Log: ${XDG_STATE_HOME:-~/.local/state}/agent-desktop/agent-desktop.log, one line per step: UTC time, run id, elapsed, step,
# outcome. `type` logs its length, not its text.
set -eu

SCRIPT_NAME="agent-desktop"
DOC="docs/agent-desktop.md"
UI_DEFAULT="$HOME/.local/share/agent-desktop/vercel/agent-desktop"

usage() {
  echo "usage: $SCRIPT_NAME shot FILE [REGION] | windows | focus NAME | move X Y |" >&2
  echo "       $SCRIPT_NAME click X Y [left|right|middle] | type TEXT | key KEY [MOD...] | cursor | ui ARGS..." >&2
  exit 2
}

fail() {  # fail EXIT_CODE MESSAGE...
  code=$1
  shift
  echo "[$SCRIPT_NAME] ERROR: $*" >&2
  exit "$code"
}

require() {  # require TOOL...: exit 69 naming the first tool that is not on PATH
  for t in "$@"; do
    if ! command -v "$t" >/dev/null 2>&1; then
      echo "[$SCRIPT_NAME] ERROR: $t is not on PATH (it ships with macOS; is this a Mac?)" >&2
      exit 69
    fi
  done
}

start_log() {
  state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/agent-desktop"
  mkdir -p "$state_dir"
  LOG="$state_dir/agent-desktop.log"
  RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
  START=$(date +%s)
}

record() {  # record TEXT: one line in the log
  printf '%s run=%s elapsed=%ss %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$RUN_ID" "$(($(date +%s) - START))" "$*" >>"$LOG"
}

prepare() {  # prepare TOOL...: check the tools and open the log. Nothing acts before this.
  require "$@"
  start_log
}

is_int() {  # is_int VALUE: optional minus, then digits only
  case $1 in
    -*) set -- "${1#-}" ;;
  esac
  case $1 in
    ''|*[!0-9]*) return 1 ;;
    *) return 0 ;;
  esac
}

is_uint() {  # is_uint VALUE: digits only
  case $1 in
    ''|*[!0-9]*) return 1 ;;
    *) return 0 ;;
  esac
}

valid_word() {  # valid_word VALUE: a key or modifier name such as comma or ctrl
  case $1 in
    ''|*[!A-Za-z0-9_]*) return 1 ;;
    *) return 0 ;;
  esac
}

# The JavaScript. No single quote may appear in it (it sits in a single-quoted string), and nothing here is built from user input.
JXA='
ObjC.import("CoreGraphics");
ObjC.import("ApplicationServices");
function point(x, y) { return $.CGPointMake(x, y); }
function post(ev) { $.CGEventPost($.kCGHIDEventTap, ev); }
function mouse(kind, x, y, button) { return $.CGEventCreateMouseEvent($(), kind, point(x, y), button); }
function warp(x, y) {
  $.CGWarpMouseCursorPosition(point(x, y));
  post(mouse($.kCGEventMouseMoved, x, y, $.kCGMouseButtonLeft));
}
function clean(v) { return String(v).replace(/[\t\n\r]/g, " "); }
function run(argv) {
  var action = argv[0];
  if (action === "preflight") {
    if (argv[1] === "screen") { return $.CGPreflightScreenCaptureAccess() ? "granted" : "denied"; }
    return $.AXIsProcessTrusted() ? "granted" : "denied";
  }
  if (action === "windows") {
    var opts = $.kCGWindowListOptionOnScreenOnly | $.kCGWindowListExcludeDesktopElements;
    var list = ObjC.deepUnwrap(ObjC.castRefToObject($.CGWindowListCopyWindowInfo(opts, $.kCGNullWindowID)));
    var rows = [];
    list.forEach(function (w) {
      if (w.kCGWindowLayer !== 0) { return; }
      var b = w.kCGWindowBounds;
      rows.push([clean(w.kCGWindowOwnerName || ""), clean(w.kCGWindowName || ""),
        Math.round(b.X) + "," + Math.round(b.Y), Math.round(b.Width) + "x" + Math.round(b.Height),
        w.kCGWindowOwnerPID].join("\t"));
    });
    return rows.join("\n");
  }
  if (action === "cursor") {
    var p = $.CGEventGetLocation($.CGEventCreate($()));
    return Math.round(p.x) + " " + Math.round(p.y);
  }
  var x = parseInt(argv[1], 10);
  var y = parseInt(argv[2], 10);
  if (action === "move") { warp(x, y); return ""; }
  if (action === "click") {
    var kinds = {
      left: [$.kCGEventLeftMouseDown, $.kCGEventLeftMouseUp, $.kCGMouseButtonLeft],
      right: [$.kCGEventRightMouseDown, $.kCGEventRightMouseUp, $.kCGMouseButtonRight],
      middle: [$.kCGEventOtherMouseDown, $.kCGEventOtherMouseUp, $.kCGMouseButtonCenter]
    };
    var k = kinds[argv[3]];
    warp(x, y);
    [0, 1].forEach(function (i) {
      var ev = mouse(k[i], x, y, k[2]);
      $.CGEventSetIntegerValueField(ev, $.kCGMouseEventClickState, 1);
      post(ev);
    });
    return "";
  }
  var se = Application("System Events");
  if (action === "focus") {
    var proc;
    try { proc = se.processes.byName(argv[1]); proc.name(); }
    catch (e) { throw new Error("no running app named " + argv[1]); }
    proc.frontmost = true;
    return "";
  }
  if (action === "type") { se.keystroke(argv[1]); return ""; }
  if (action === "key") {
    var mods = argv.slice(2).map(function (m) { return m + " down"; });
    if (mods.length > 0) { se.keyCode(parseInt(argv[1], 10), { using: mods }); }
    else { se.keyCode(parseInt(argv[1], 10)); }
    return "";
  }
  throw new Error("unknown action " + action);
}
'

osa() {  # osa ACTION [ARG...]: run the JavaScript. Sets OSA_RC, OSA_OUT (stdout) and OSA_ERR (stderr).
  errfile="$state_dir/osascript.err.$$"
  OSA_RC=0
  OSA_OUT=$(osascript -l JavaScript -e "$JXA" "$@" 2>"$errfile") || OSA_RC=$?
  OSA_ERR=$(cat "$errfile")
  rm -f "$errfile"
}

denied() {  # denied screen|accessibility: exit 1 with a message that names the permission and the doc
  case $1 in
    screen) what="Screen Recording" ;;
    *) what="Accessibility" ;;
  esac
  record "FAIL permission $what"
  fail 1 "$what is not allowed for this session, so macOS would drop the request or blank its result. Allow /usr/libexec/sshd-keygen-wrapper under System Settings, Privacy & Security, $what. Steps: $DOC"
}

allowed() {  # allowed screen|accessibility: continue only when the system says the grant is there
  osa preflight "$1"
  if [ "$OSA_RC" -ne 0 ]; then
    record "FAIL permission check ($1)"
    fail 1 "could not check the $1 permission: ${OSA_ERR:-osascript failed (exit $OSA_RC)}"
  fi
  [ "$OSA_OUT" = granted ] || denied "$1"
}

act() {  # act STEP ACTION [ARG...]: run an osascript action that returns nothing; log STEP
  step=$1
  shift
  osa "$@"
  if [ "$OSA_RC" -ne 0 ]; then
    record "FAIL $step"
    case $OSA_ERR in
      *"not allowed"*|*assistive*|*-25211*|*1002*) denied accessibility ;;
      *) fail 1 "${OSA_ERR:-osascript failed (exit $OSA_RC)}" ;;
    esac
  fi
  record "$step"
}

parse_region() {  # parse_region REGION: "X,Y WxH" with whole numbers, else exit 2. Sets REGION_RECT to "X,Y,W,H".
  case $1 in
    *' '*) ;;
    *) fail 2 "shot: REGION must be \"X,Y WxH\"" ;;
  esac
  xy=${1%% *}
  wh=${1#* }
  case $xy in *,*) ;; *) fail 2 "shot: REGION must be \"X,Y WxH\"" ;; esac
  case $wh in *x*) ;; *) fail 2 "shot: REGION must be \"X,Y WxH\"" ;; esac
  rx=${xy%,*}
  ry=${xy#*,}
  rw=${wh%x*}
  rh=${wh#*x}
  if ! is_int "$rx" || ! is_int "$ry" || ! is_uint "$rw" || ! is_uint "$rh"; then
    fail 2 "shot: REGION must be \"X,Y WxH\" with whole numbers"
  fi
  REGION_RECT="$rx,$ry,$rw,$rh"
}

cmd_shot() {  # FILE [REGION]
  file=$1
  region=${2:-}
  allowed screen
  if [ -n "$region" ]; then
    set -- -x -R "$REGION_RECT" "$file"
  else
    set -- -x "$file"
  fi
  rc=0
  screencapture "$@" || rc=$?
  if [ "$rc" -ne 0 ] || [ ! -s "$file" ]; then
    record "FAIL shot $file region=${region:-full} exit=$rc"
    fail 1 "screencapture did not write $file (exit $rc). The usual cause is a missing Screen Recording permission for /usr/libexec/sshd-keygen-wrapper. Steps: $DOC"
  fi
  record "shot $file region=${region:-full}"
  echo "$file"
}

cmd_windows() {
  allowed screen
  osa windows
  if [ "$OSA_RC" -ne 0 ]; then
    record "FAIL windows"
    fail 1 "could not list the windows: ${OSA_ERR:-osascript failed (exit $OSA_RC)}"
  fi
  record "windows"
  printf 'app\ttitle\tat\tsize\tpid\n'
  if [ -n "$OSA_OUT" ]; then printf '%s\n' "$OSA_OUT"; fi
}

cmd_cursor() {
  osa cursor
  if [ "$OSA_RC" -ne 0 ]; then
    record "FAIL cursor"
    fail 1 "could not read the pointer: ${OSA_ERR:-osascript failed (exit $OSA_RC)}"
  fi
  case $OSA_OUT in
    *' '*) ;;
    *) record "FAIL cursor output=$OSA_OUT"; fail 1 "unexpected pointer output: $OSA_OUT" ;;
  esac
  x=${OSA_OUT%% *}
  y=${OSA_OUT#* }
  if is_int "$x" && is_int "$y"; then
    record "cursor $x $y"
    echo "$x $y"
  else
    record "FAIL cursor output=$OSA_OUT"
    fail 1 "unexpected pointer output: $OSA_OUT"
  fi
}

key_code() {  # key_code NAME: print the macOS key code for a US-layout key name, or return 1
  name=$(printf '%s' "$1" | tr 'A-Z' 'a-z')
  case $name in
    a) echo 0 ;; s) echo 1 ;; d) echo 2 ;; f) echo 3 ;; h) echo 4 ;; g) echo 5 ;; z) echo 6 ;; x) echo 7 ;;
    c) echo 8 ;; v) echo 9 ;; b) echo 11 ;; q) echo 12 ;; w) echo 13 ;; e) echo 14 ;; r) echo 15 ;; y) echo 16 ;;
    t) echo 17 ;; o) echo 31 ;; u) echo 32 ;; i) echo 34 ;; p) echo 35 ;; l) echo 37 ;; j) echo 38 ;; k) echo 40 ;;
    n) echo 45 ;; m) echo 46 ;;
    1) echo 18 ;; 2) echo 19 ;; 3) echo 20 ;; 4) echo 21 ;; 5) echo 23 ;; 6) echo 22 ;; 7) echo 26 ;; 8) echo 28 ;;
    9) echo 25 ;; 0) echo 29 ;;
    equal) echo 24 ;; minus) echo 27 ;; bracketright|rightbracket) echo 30 ;; bracketleft|leftbracket) echo 33 ;;
    apostrophe|quote) echo 39 ;; semicolon) echo 41 ;; backslash) echo 42 ;; comma) echo 43 ;; slash) echo 44 ;;
    period) echo 47 ;; grave) echo 50 ;;
    return|enter) echo 36 ;; tab) echo 48 ;; space) echo 49 ;; backspace|delete) echo 51 ;; escape|esc) echo 53 ;;
    left) echo 123 ;; right) echo 124 ;; down) echo 125 ;; up) echo 126 ;;
    home) echo 115 ;; end) echo 119 ;; pageup|prior) echo 116 ;; pagedown|next) echo 121 ;; forwarddelete) echo 117 ;;
    f1) echo 122 ;; f2) echo 120 ;; f3) echo 99 ;; f4) echo 118 ;; f5) echo 96 ;; f6) echo 97 ;; f7) echo 98 ;;
    f8) echo 100 ;; f9) echo 101 ;; f10) echo 109 ;; f11) echo 103 ;; f12) echo 111 ;;
    *) return 1 ;;
  esac
}

modifier_name() {  # modifier_name NAME: print the System Events modifier for a modifier name, or return 1
  name=$(printf '%s' "$1" | tr 'A-Z' 'a-z')
  case $name in
    ctrl|control) echo control ;;
    shift) echo shift ;;
    alt|option|opt) echo option ;;
    cmd|command|super|logo) echo command ;;
    *) return 1 ;;
  esac
}

cmd_ui() {  # ARGS...: Vercel's program, output and exit code unchanged
  start_log
  bin=${AGENT_DESKTOP_UI_BIN:-$UI_DEFAULT}
  if [ ! -x "$bin" ]; then
    record "FAIL ui (no program at $bin)"
    fail 69 "Vercel's agent-desktop is not installed at $bin. A dotfiles apply installs it (run_onchange_after_66_agent_desktop_macos.sh.tmpl); to run the step by hand see $DOC"
  fi
  rc=0
  "$bin" "$@" || rc=$?
  record "ui args=$# exit=$rc"
  exit "$rc"
}

[ $# -ge 1 ] || usage
cmd=$1
shift
case $cmd in
  shot)
    [ $# -ge 1 ] && [ $# -le 2 ] || usage
    [ -n "$1" ] || fail 2 "shot: FILE must not be empty"
    if [ $# -eq 2 ]; then parse_region "$2"; fi
    prepare screencapture osascript
    cmd_shot "$@" ;;
  windows)
    [ $# -eq 0 ] || usage
    prepare osascript
    cmd_windows ;;
  focus)
    [ $# -eq 1 ] || usage
    [ -n "$1" ] || fail 2 "focus: NAME must not be empty"
    prepare osascript
    allowed accessibility
    act "focus $1" focus "$1" ;;
  move)
    [ $# -eq 2 ] || usage
    if ! is_int "$1" || ! is_int "$2"; then fail 2 "move: X and Y must be integers"; fi
    prepare osascript
    allowed accessibility
    act "move $1 $2" move "$1" "$2" ;;
  click)
    [ $# -eq 2 ] || [ $# -eq 3 ] || usage
    if ! is_int "$1" || ! is_int "$2"; then fail 2 "click: X and Y must be integers"; fi
    case ${3:-left} in
      left|right|middle) ;;
      *) fail 2 "click: button must be left, right or middle" ;;
    esac
    prepare osascript
    allowed accessibility
    act "click $1 $2 ${3:-left}" click "$1" "$2" "${3:-left}" ;;
  type)
    [ $# -eq 1 ] || usage
    prepare osascript
    allowed accessibility
    act "type length=${#1}" type "$1" ;;
  key)
    [ $# -ge 1 ] || usage
    for w in "$@"; do
      valid_word "$w" || fail 2 "key: KEY and MOD must be names such as comma or ctrl"
    done
    keyname=$1
    shift
    code=$(key_code "$keyname") || fail 2 "key: unknown key $keyname"
    mods=""
    for m in "$@"; do
      canon=$(modifier_name "$m") || fail 2 "key: unknown modifier $m (ctrl, shift, alt, cmd)"
      mods="${mods:+$mods }$canon"
    done
    prepare osascript
    allowed accessibility
    # shellcheck disable=SC2086
    act "key $keyname mods=${mods:-none}" key "$code" $mods ;;
  cursor)
    [ $# -eq 0 ] || usage
    prepare osascript
    cmd_cursor ;;
  ui)
    cmd_ui "$@" ;;
  *)
    usage ;;
esac
