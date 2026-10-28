#!/bin/sh
# work-mac-instances.sh: bring the work Mac's dotfiles up to the work Matrix coordinator instance (dotfiles PR #80, 85aab1c), step by step and safely.
#
#   sh work-mac-instances.sh --dry-run                  show what would be done; changes nothing
#   sh work-mac-instances.sh [--coordinator DIR]        steps 1 to 4: pull, local data, inert unit, compare with the live unit. Does not change the flag.
#   sh work-mac-instances.sh --enable [--coordinator DIR]   also step 5: turn the flag on and apply (adopts the running service, no restart)
#   (--allow-hooks: accept chezmoi hooks other than the 1Password installer, after you have read them; step 1 lists them)
#
# What it touches: the dotfiles source (git fast-forward only; stops if it has tracked changes or cannot fast-forward), the local chezmoi
# config file (a timestamped backup first; it only ADDS missing keys, and with --enable flips instances.coordinator.enabled to true), and, through
# "chezmoi apply" limited to three targets, the inert unit under ~/.local/share/instances/launchd, ~/.local/user_scripts/instances_reconcile.sh and
# (--enable only) the reconcile step. It never uses sudo, never runs the coordinator's setup script, never reads or prints a secret, never edits the
# live unit in ~/Library/LaunchAgents, and calls launchctl only through "print" (read-only) and, in step 5, the dotfiles reconcile script.
# Every chezmoi command that reads the dotfiles source runs the hooks of your chezmoi config. Step 1 lists them WITHOUT running them and stops
# unless each is the dotfiles' 1Password installer with op already installed (then it does nothing) or you pass --allow-hooks.
# Values from the live unit: if no checkout is given (--coordinator, COORDINATOR_DIR) and your chezmoi data has no instances.coordinator.repo, the checkout is the
# WorkingDirectory of the installed ~/Library/LaunchAgents/local.coordinatord.work.plist (read-only), else ~/git/coordinator. If the live unit differs from the
# rendered one only by a PATH prefix and instances.coordinator.extraPath is unset, that prefix is ADDED as extraPath (backup first, read back, never an
# overwrite). Anything it cannot read or trust there stops the run with the lines to add by hand. --dry-run renders the unit against a copy of the config
# (chezmoi --config), so it needs no --override-data.
# --enable also refuses to run if INSTANCES_RELOAD, INSTANCES_STATE_ROOT, INSTANCES_AGENTS_DIR or INSTANCES_UNIT_DIR is set in the environment,
# or if the coordinator-work.configuring marker exists (either would make the reconcile step restart the service or run the setup script).
#
# Exit codes: 0 everything asked for succeeded; 1 a step failed; 2 bad usage; 4 you must do one thing by hand (it says what) and re-run;
# 5 --enable applied but the instance reports NOT READY (the flag stays on; fix the reason and re-run, or set enabled: false and apply).
set -u

DRY=0; ENABLE=0; ALLOW_HOOKS=0; COORD_ARG=''
WORK_PROFILE=axon-work-computer
UNIT_NAME=local.coordinatord.work
UNIT_REL=.local/share/instances/launchd/$UNIT_NAME.plist
SCRIPT_REL=.local/user_scripts/instances_reconcile.sh
WRAPPER_REL=75_instances_reconcile.sh
SELF=$0

say() { printf '%s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
ok() { printf '   [ok]     %s\n' "$*"; }
info() { printf '   [info]   %s\n' "$*"; }
would() { printf '   [would]  %s\n' "$*"; }
do_() { printf '   [do]     %s\n' "$*"; }
fail() { # fail MESSAGE [HINT...]: exit 1
  printf '   [FAIL]   %s\n' "$1" >&2; shift
  for _l in "$@"; do printf '            %s\n' "$_l" >&2; done
  exit 1
}
action() { # action MESSAGE [LINE...]: something only you can do; exit 4
  printf '   [ACTION] %s\n' "$1" >&2; shift
  for _l in "$@"; do printf '            %s\n' "$_l" >&2; done
  exit 4
}
usage() { sed -n '2,7p' "$SELF" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case $1 in
    --dry-run) DRY=1;;
    --enable) ENABLE=1;;
    --allow-hooks) ALLOW_HOOKS=1;;
    --coordinator) [ $# -ge 2 ] || { echo "--coordinator needs a directory" >&2; exit 2; }; COORD_ARG=$2; shift;;
    --coordinator=*) COORD_ARG=${1#--coordinator=};;
    -h|--help) usage; exit 0;;
    *) echo "unknown option: $1 (try --help)" >&2; exit 2;;
  esac
  shift
done
[ -z "$COORD_ARG" ] && COORD_ARG=${COORDINATOR_DIR:-}

[ "$(id -u)" != 0 ] || fail "do not run this with sudo or as root." "Run it as yourself."
for _v in INSTANCES_RELOAD INSTANCES_STATE_ROOT INSTANCES_AGENTS_DIR INSTANCES_UNIT_DIR; do
  eval "_val=\${$_v:-}"
  [ -z "$_val" ] || fail "$_v is set in your environment; the dotfiles reconcile step would obey it (restart, other directories)." "Unset it and re-run: unset $_v"
done
[ "$(uname -s)" = Darwin ] || fail "this is for the work Mac (macOS); this is $(uname -s)."
[ -n "${HOME:-}" ] && [ -d "$HOME" ] || fail "HOME is not set to a directory."
# The read-source-state hook in a typical chezmoi config uses a path relative to the home directory.
cd "$HOME" || fail "cannot change to $HOME."
TMP=$(mktemp -d "${TMPDIR:-/tmp}/work-mac-instances.XXXXXX") || fail "cannot make a temporary directory."
HAVE_LOCK=0; LOCKDIR=''
trap 'rm -rf "$TMP"; if [ "$HAVE_LOCK" = 1 ]; then rmdir "$LOCKDIR" 2>/dev/null; fi' EXIT
trap 'exit 1' HUP INT TERM
BACKUP=''; DERIVED_EXTRA=0; LIVE_NOTE=''

if [ "$DRY" = 1 ]; then say "work-mac-instances: DRY RUN, nothing is changed"; else say "work-mac-instances: applying"; fi
if [ "$ENABLE" = 1 ]; then say "(--enable: step 5 will turn the flag on)"; else say "(no --enable: this script does not change instances.coordinator.enabled; step 5 is not run)"; fi

rp() { (cd "$1" 2>/dev/null && pwd -P); }
LIVE=$HOME/Library/LaunchAgents/$UNIT_NAME.plist
# Read-only readers of a unit file (the rendered and the live one have the layout of the template, one key per line).
plist_path() { sed -n 's|.*<key>PATH</key><string>\(.*\)</string>.*|\1|p' "$1" | head -n 1; }
plist_wd() { sed -n 's|.*<key>WorkingDirectory</key><string>\(.*\)</string>.*|\1|p' "$1" | head -n 1; }
norm() { sed 's|\(<key>PATH</key><string>\)[^<]*|\1@PATH@|' "$1"; }
# Values taken from the live unit end up in YAML and in an XML template: refuse the characters that would need escaping.
safe_chars() { case $1 in *'&'*|*'<'*|*'>'*|*'"'*|*"'"*|*\\*) return 1;; esac; return 0; }
prefix_ok() { # absolute directories joined by single colons
  safe_chars "$1" || return 1
  case $1 in ''|*::*|*:|:*) return 1;; esac
  _oifs=$IFS; IFS=:; set -f
  for _d in $1; do case $_d in /*) ;; *) IFS=$_oifs; set +f; return 1;; esac; done
  IFS=$_oifs; set +f; return 0
}
coord_ok() { # a usable coordinator checkout: absolute, plain characters, a git work tree with the daemon's main.ts
  case $1 in /*) ;; *) return 1;; esac
  safe_chars "$1" || return 1
  [ -d "$1" ] && [ -f "$1/src/coordinatord/main.ts" ] && git -C "$1" rev-parse --is-inside-work-tree >/dev/null 2>&1
}
# tmpl TEMPLATE: the value of a chezmoi template, taken from between markers (hook output around it is ignored)
tmpl() {
  chezmoi execute-template "@@$1@@" >"$TMP/tmpl.out" 2>"$TMP/tmpl.err" || return 1
  sed -n 's/^.*@@\(.*\)@@.*$/\1/p' "$TMP/tmpl.out" | tail -n 1
}
cdata() { # cdata KEY...: a local data value, "" when unset
  _t='{{ dig'; for _k in "$@"; do _t="$_t \"$_k\""; done; _t="$_t \"\" . }}"
  tmpl "$_t" || fail "cannot read local chezmoi data ($*)." "$(head -n 3 "$TMP/tmpl.err")"
}

# ---------------------------------------------------------------------------------------------------------------------------------------
step "1. Preflight: tools, dotfiles source, coordinator checkout"
for _c in chezmoi git awk sed diff cmp cp mv grep date mktemp; do
  command -v "$_c" >/dev/null 2>&1 || fail "$_c is not on PATH." "chezmoi: https://www.chezmoi.io/install/ ; the others come with macOS or the Xcode command line tools."
done
ok "chezmoi, git and the usual tools are present"

# Hooks first: "chezmoi dump-config" does not read the source, so it does not run them.
chezmoi dump-config --format json >"$TMP/cfg.json" 2>"$TMP/err" || fail "cannot read the chezmoi configuration." "$(head -n 3 "$TMP/err")"
awk '/^  "hooks": \{\},?$/ { next } /^  "hooks": \{/ { on = 1; next } on && /^  \}/ { on = 0 } on && /"(command|script)": "[^"]+"/ { s = $0; sub(/^[^:]*: "/, "", s); sub(/",?$/, "", s); print s }' "$TMP/cfg.json" >"$TMP/hooks"
if [ ! -s "$TMP/hooks" ]; then ok "no chezmoi hooks are configured"
else
  BADHOOK=''
  # The installer is trusted only at its audited place: the default checkout, which is also the chezmoi source (it sources utils.sh from there).
  SRCDIR=$(sed -n 's/^  "sourceDir": "\(.*\)",\{0,1\}$/\1/p' "$TMP/cfg.json" | head -n 1)
  DEFAULT_SRC=$(rp "$HOME/.local/share/chezmoi")
  while IFS= read -r _h; do
    case $_h in /*) _hp=$_h;; *) _hp=$HOME/$_h;; esac
    _hd=$(rp "$(dirname "$_hp")")
    case $_h in
      */.install-password-manager.sh|.install-password-manager.sh)
        if [ -z "$DEFAULT_SRC" ] || [ "$_hd" != "$DEFAULT_SRC" ] || [ "$(rp "$SRCDIR")" != "$DEFAULT_SRC" ] || [ ! -f "$_hp" ]; then
          if [ "$ALLOW_HOOKS" = 1 ]; then info "hook $_h is not the installer in the default checkout (allowed by --allow-hooks)"
          else BADHOOK="$BADHOOK $_h (not the installer at the default checkout ~/.local/share/chezmoi, or the chezmoi source is elsewhere)"; fi
        elif command -v op >/dev/null 2>&1; then ok "hook $_h (the 1Password installer; op is installed, so it does nothing)"
        elif [ "$ALLOW_HOOKS" = 1 ]; then info "hook $_h would install the 1Password CLI (op is missing); allowed by --allow-hooks"
        else BADHOOK="$BADHOOK $_h (would run brew install 1password-cli: op is not on PATH)"; fi;;
      *) if [ "$ALLOW_HOOKS" = 1 ]; then info "hook $_h (allowed by --allow-hooks)"; else BADHOOK="$BADHOOK $_h"; fi;;
    esac
  done <"$TMP/hooks"
  [ -z "$BADHOOK" ] || fail "your chezmoi config has hooks that run on every chezmoi command, and this script cannot show them to be harmless:$BADHOOK" "Read them; if they are fine, re-run with --allow-hooks. Nothing was changed."
fi

SRC=$(chezmoi source-path 2>"$TMP/err") || fail "chezmoi cannot find its source directory." "$(head -n 3 "$TMP/err")"
[ -d "$SRC" ] || fail "the chezmoi source directory $SRC does not exist."
TOP=$(git -C "$SRC" rev-parse --show-toplevel 2>/dev/null) || fail "the chezmoi source $SRC is not a git checkout." "This script needs it to be one, to bring in the work-instance change."
ok "dotfiles source: $SRC (git: $TOP)"
BRANCH=$(git -C "$TOP" symbolic-ref -q --short HEAD) || fail "the dotfiles source is on a detached HEAD." "Check out your branch (usually main): git -C $TOP checkout main"
UPSTREAM=$(git -C "$TOP" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null) || fail "branch $BRANCH of the dotfiles source has no upstream." "Set it: git -C $TOP branch --set-upstream-to=origin/$BRANCH"
DIRTY=$(git -C "$TOP" --no-optional-locks status --porcelain --untracked-files=no 2>/dev/null) || fail "cannot read the git status of $TOP."
if [ -n "$DIRTY" ]; then
  fail "the dotfiles source has uncommitted changes to tracked files; not touching it." "$(printf '%s\n' "$DIRTY" | head -n 8)" "Commit, stash or discard them (git -C $TOP status), then re-run."
fi
ok "branch $BRANCH tracks $UPSTREAM, no tracked changes"
export GIT_TERMINAL_PROMPT=0
if [ "$DRY" = 1 ]; then
  # A dry run fetches nothing (even "git fetch --dry-run" can write objects); it only asks the remote for its tip.
  _rem=$(git -C "$TOP" config "branch.$BRANCH.remote") || _rem=origin
  _mrg=$(git -C "$TOP" config "branch.$BRANCH.merge") || _mrg=refs/heads/$BRANCH
  _tip=$(git -C "$TOP" ls-remote "$_rem" "$_mrg" 2>"$TMP/fetch.out") || fail "cannot reach the dotfiles remote." "$(head -n 3 "$TMP/fetch.out")" "Check the network or VPN."
  _tip=$(printf '%s' "$_tip" | awk 'NR == 1 { print $1 }')
  if [ -n "$_tip" ] && [ "$_tip" != "$(git -C "$TOP" rev-parse "$UPSTREAM")" ]; then would "git fetch: the remote has newer commits than the last fetch; then fast-forward $BRANCH (a dry run does not fetch)"
  else would "git fetch (the remote has nothing newer than the last fetch)"; fi
else
  git -C "$TOP" fetch --quiet >"$TMP/fetch.out" 2>&1 || fail "cannot reach the dotfiles remote." "$(head -n 3 "$TMP/fetch.out")" "Check the network or VPN."
fi
LOCAL=$(git -C "$TOP" rev-parse HEAD); UP=$(git -C "$TOP" rev-parse "$UPSTREAM")
if [ "$LOCAL" = "$UP" ]; then
  ok "dotfiles source is up to date ($(git -C "$TOP" rev-parse --short HEAD))"
elif git -C "$TOP" merge-base --is-ancestor "$LOCAL" "$UP"; then
  _n=$(git -C "$TOP" rev-list --count "$LOCAL..$UP")
  if [ "$DRY" = 1 ]; then would "fast-forward $_n commit(s)"
  else
    do_ "fast-forward $_n commit(s)"
    git -C "$TOP" merge --ff-only --quiet "$UPSTREAM" >"$TMP/merge.out" 2>&1 || fail "the fast-forward failed." "$(head -n 3 "$TMP/merge.out")"
    ok "dotfiles source is now at $(git -C "$TOP" rev-parse --short HEAD)"
  fi
elif git -C "$TOP" merge-base --is-ancestor "$UP" "$LOCAL"; then
  info "the dotfiles source has local commits that $UPSTREAM does not; nothing to pull"
else
  fail "the dotfiles source and $UPSTREAM have diverged (not a fast-forward); not touching it." "Look at: git -C $TOP log --oneline --left-right $BRANCH...$UPSTREAM"
fi
TEMPLATE=$SRC/dot_local/share/instances/launchd/$UNIT_NAME.plist.tmpl
if [ ! -f "$TEMPLATE" ] || [ ! -f "$SRC/run_after_75_instances_reconcile.sh.tmpl" ]; then
  if [ "$DRY" = 1 ]; then info "the work coordinator instance is not in the source yet (it arrives with the pull)"
  else fail "the dotfiles source has no work coordinator instance (dotfiles PR #80, 85aab1c, or later)." "Is $UPSTREAM the cartwmic/dotfiles main branch?"; fi
fi

DESTDIR=$(tmpl '{{ .chezmoi.destDir }}') || fail "cannot read chezmoi's destination directory." "$(head -n 3 "$TMP/tmpl.err")"
[ "$(rp "$DESTDIR")" = "$(rp "$HOME")" ] || fail "chezmoi's destination directory is $DESTDIR, not $HOME; this script assumes the home directory."

DATA_REPO=$(cdata instances coordinator repo)
COORD_SRC=''
if [ -n "$COORD_ARG" ]; then COORD=$COORD_ARG; COORD_SRC='argument or COORDINATOR_DIR'
elif [ -n "$DATA_REPO" ]; then COORD=$DATA_REPO; COORD_SRC='instances.coordinator.repo in your chezmoi data'
else
  # Nothing given: the checkout the installed live unit runs from (read-only), else the default.
  COORD=$HOME/git/coordinator; COORD_SRC='default'; LIVE_NOTE='there is no live unit to read it from'
  if [ -f "$LIVE" ]; then
    _lwd=$(plist_wd "$LIVE")
    if [ -z "$_lwd" ]; then LIVE_NOTE="the live unit $LIVE has no WorkingDirectory"
    elif coord_ok "$_lwd"; then COORD=$_lwd; COORD_SRC="derived from the WorkingDirectory of the live unit $LIVE (read-only); nothing was passed and your chezmoi data has no repo"
    else LIVE_NOTE="the WorkingDirectory of the live unit, [$_lwd], is not a usable coordinator checkout"; fi
  fi
fi
case $COORD in \~) COORD=$HOME;; \~/*) COORD=$HOME/${COORD#\~/};; esac
case $COORD in /*) ;; *) fail "the coordinator checkout path must be absolute: $COORD";; esac
case $COORD in *\"*|*\\*) fail "the coordinator checkout path has a quote or backslash, which this script does not handle: $COORD";; esac
[ -d "$COORD" ] || fail "the coordinator checkout $COORD does not exist ($COORD_SRC)." "Clone cartwmic/coordinator there by hand (dotfiles never clones), or pass --coordinator DIR." ${LIVE_NOTE:+"Not derived from the live unit: $LIVE_NOTE."}
git -C "$COORD" rev-parse --is-inside-work-tree >/dev/null 2>&1 || fail "$COORD is not a git checkout." "Pass the directory of your cartwmic/coordinator clone: --coordinator DIR"
[ -f "$COORD/src/coordinatord/main.ts" ] || fail "$COORD is not the coordinator repository (src/coordinatord/main.ts is missing)." "Pass the directory of your cartwmic/coordinator clone: --coordinator DIR"
COORD_REAL=$(rp "$COORD")
ok "coordinator checkout: $COORD_REAL ($COORD_SRC)"

# ---------------------------------------------------------------------------------------------------------------------------------------
step "2. Local chezmoi data"
CONFIG=$(tmpl '{{ .chezmoi.configFile }}') || CONFIG=''
[ -n "$CONFIG" ] || CONFIG=$HOME/.config/chezmoi/chezmoi.yaml
[ -f "$CONFIG" ] || fail "your chezmoi config $CONFIG does not exist." "This script does not create it. Create it as the dotfiles README describes, then re-run."
case $CONFIG in *.yaml|*.yml) ;; *) fail "your chezmoi config is $CONFIG, which is not YAML; this script edits YAML only." "Add by hand under data: profile, and instances.coordinator.repo (see the dotfiles README, section Instances).";; esac
if [ -L "$CONFIG" ]; then
  _lt=$(readlink "$CONFIG") || fail "cannot read the link $CONFIG."
  case $_lt in /*) ;; *) _lt=$(dirname "$CONFIG")/$_lt;; esac
  CONFIG=$_lt
  [ -f "$CONFIG" ] && [ ! -L "$CONFIG" ] || fail "your chezmoi config is a chain of links; this script follows one link only: $CONFIG"
fi
[ -w "$CONFIG" ] || fail "your chezmoi config $CONFIG is not writable."
if [ "$DRY" != 1 ]; then
  LOCKDIR=$CONFIG.wmi-lock
  mkdir "$LOCKDIR" 2>/dev/null || fail "another run of this script holds $LOCKDIR, or an earlier run was killed." "If no other run is active, remove it: rmdir $LOCKDIR"
  HAVE_LOCK=1
fi
PROFILE=$(cdata profile); ENABLED=$(cdata instances coordinator enabled); EXTRA=$(cdata instances coordinator extraPath)
ok "config file: $CONFIG"
if [ "$ENABLED" = true ] && [ "$ENABLE" != 1 ]; then info "NOTE: instances.coordinator.enabled is ALREADY true in your config; the reconcile step runs on the next full chezmoi apply, or with --enable here."; fi
info "profile=[$PROFILE] instances.coordinator.repo=[$DATA_REPO] enabled=[$ENABLED] extraPath=[$EXTRA]"
if [ -n "$PROFILE" ] && [ "$PROFILE" != "$WORK_PROFILE" ]; then
  fail "the profile in your chezmoi data is '$PROFILE', not $WORK_PROFILE; this script is for the work Mac and will not change it."
fi
if [ -n "$DATA_REPO" ] && [ -n "$COORD_ARG" ] && [ "$DATA_REPO" != "$COORD_REAL" ] && [ "$(rp "$DATA_REPO")" != "$COORD_REAL" ]; then
  fail "instances.coordinator.repo is already $DATA_REPO in $CONFIG, but you asked for $COORD_REAL." "This script never overwrites an existing value. Edit the file by hand, or drop the argument."
fi

cat >"$TMP/edit.awk" <<'AWK'
function ind(s,   i) { i = 1; while (substr(s, i, 1) == " ") i++; return i - 1 }
function blank(s) { return s ~ /^[ ]*(#.*)?$/ }
function spaces(n,   r) { r = ""; while (n-- > 0) r = r " "; return r }
function stripc(s) { sub(/[ ]+#.*$/, "", s); sub(/^[ ]+/, "", s); sub(/[ ]+$/, "", s); return s }
function dump(   i) { for (i = 1; i <= NR; i++) print L[i] }
{ L[NR] = $0 }
END {
  n = split(keys, K, " ")
  depth = 0; matched = 0; mline = 0; mind = 0; mrest = ""
  for (i = 1; i <= NR; i++) {
    s = L[i]
    if (blank(s)) continue
    c = ind(s); t = substr(s, c + 1)
    while (depth > 0 && SI[depth] >= c) depth--
    if (t ~ /^-/) continue
    if (t !~ /^[A-Za-z0-9_.-]+:([ ]|$)/) continue
    p = index(t, ":"); key = substr(t, 1, p - 1); rest = substr(t, p + 1)
    depth++; SI[depth] = c; SK[depth] = key
    if (depth <= n) {
      good = 1
      for (j = 1; j <= depth; j++) if (SK[j] != K[j]) { good = 0; break }
      if (good && depth > matched) { matched = depth; mline = i; mind = c; mrest = rest }
    }
  }
  if (matched == n) {
    if (mode == "add") { dump(); print "exists" > st; exit 0 }
    r = mrest; cm = ""
    if (match(r, /[ ]+#/)) { cm = substr(r, RSTART); r = substr(r, 1, RSTART - 1) }
    r = stripc(r)
    if (r == "") { dump(); print "manual" > st; exit 3 }
    if (r == val) { dump(); print "same" > st; exit 0 }
    for (i = 1; i <= NR; i++) { if (i == mline) print spaces(mind) K[n] ": " val cm; else print L[i] }
    print "changed" > st; exit 0
  }
  if (matched == 0) {
    dump()
    for (m = 1; m <= n; m++) print spaces((m - 1) * 2) K[m] ":" (m == n ? " " val : "")
    print "added" > st; exit 0
  }
  if (stripc(mrest) != "") { dump(); print "manual" > st; exit 3 }
  childInd = mind + 2
  for (j = mline + 1; j <= NR; j++) {
    if (blank(L[j])) continue
    if (ind(L[j]) > mind) { childInd = ind(L[j]); if (substr(L[j], childInd + 1, 1) == "-") { dump(); print "manual" > st; exit 3 } }
    break
  }
  step = childInd - mind
  for (i = 1; i <= NR; i++) {
    print L[i]
    if (i == mline) for (m = matched + 1; m <= n; m++) print spaces(childInd + (m - matched - 1) * step) K[m] ":" (m == n ? " " val : "")
  }
  print "added" > st
}
AWK

CUR=$TMP/cur.yaml; ORIG=$TMP/orig.yaml
cp "$CONFIG" "$ORIG" || fail "cannot read $CONFIG."
cp "$ORIG" "$CUR" || fail "cannot copy $ORIG."
EDITS=''
yaml_edit() { # yaml_edit MODE "k1 k2 ..." VALUE-AS-YAML: edits $CUR (via a temporary) and sets EDIT_STATUS; returns 3 for a layout it will not edit
  # Anchors, aliases, merge keys and block scalars could make one edit change other settings (or hide a key); leave such files to the owner.
  if grep -Eq '(^|[[:space:]:,{[-])[&*][A-Za-z0-9_-]+|^[[:space:]]*<<:|:[[:space:]]*[|>][-+0-9]*[[:space:]]*(#.*)?$' "$CUR"; then EDIT_STATUS=manual; return 3; fi
  awk -v mode="$1" -v keys="$2" -v val="$3" -v st="$TMP/status" -f "$TMP/edit.awk" "$CUR" >"$TMP/next.yaml"; _rc=$?
  EDIT_STATUS=$(cat "$TMP/status" 2>/dev/null); rm -f "$TMP/status"
  if [ "$_rc" = 3 ] || [ "$EDIT_STATUS" = manual ]; then return 3; fi
  [ "$_rc" = 0 ] || return 1
  cp "$TMP/next.yaml" "$CUR"
}
manual_edit() { # manual_edit KEY-DESCRIPTION SNIPPET...
  _what=$1; shift
  action "cannot safely add $_what to $CONFIG with an automatic edit (its layout is not plain block YAML, or the key exists with an empty value)." \
    "Add it by hand under data: and re-run. Nothing was changed. For example:" "$@"
}
if [ -z "$PROFILE" ]; then
  yaml_edit add "data profile" "\"$WORK_PROFILE\""; _r=$?
  { [ "$_r" = 0 ] && [ "$EDIT_STATUS" = added ]; } || manual_edit "profile" 'data:' "  profile: \"$WORK_PROFILE\""
  EDITS="$EDITS profile"
fi
if [ -z "$DATA_REPO" ]; then
  yaml_edit add "data instances coordinator repo" "\"$COORD_REAL\""; _r=$?
  { [ "$_r" = 0 ] && [ "$EDIT_STATUS" = added ]; } || manual_edit "instances.coordinator.repo" 'data:' '  instances:' '    coordinator:' "      repo: \"$COORD_REAL\""
  EDITS="$EDITS instances.coordinator.repo"
fi

install_config() { # install_config SOURCE TAG: replace $CONFIG by SOURCE through a same-directory temporary file and a rename (checked; the mode is kept)
  _new=$CONFIG.$2.$$
  cp -p "$CONFIG" "$_new" 2>/dev/null || return 1
  if cat "$1" >"$_new" && mv -f "$_new" "$CONFIG"; then return 0; fi
  rm -f "$_new"; return 1
}
backup_config() { # once per run, before the first write; the file is created exclusively
  [ -z "$BACKUP" ] || return 0
  _s=$(date +%Y%m%d-%H%M%S); _i=0; _b=$CONFIG.bak.$_s
  until ( set -C; : >"$_b" ) 2>/dev/null; do
    _i=$((_i + 1)); _b=$CONFIG.bak.$_s.$_i
    [ "$_i" -lt 100 ] || fail "cannot create a backup file next to $CONFIG."
  done
  cp -p "$CONFIG" "$_b" || { rm -f "$_b"; fail "cannot back up $CONFIG to $_b; not editing it."; }
  cmp -s "$CONFIG" "$_b" || fail "the backup $_b does not match $CONFIG; not editing it."
  BACKUP=$_b
  ok "backed up $CONFIG to $BACKUP"
}
# write_config EXPECTED_CHANGED: $CUR becomes the config. Existing lines may only be kept (0) or exactly one replaced (1).
write_config() {
  cmp -s "$CONFIG" "$ORIG" || fail "$CONFIG changed while this script was running; not writing it." "Nothing was changed by this script. Re-run."
  diff "$ORIG" "$CUR" >"$TMP/config.diff"
  _gone=$(grep -c '^<' "$TMP/config.diff")
  [ "$_gone" = "$1" ] || fail "the edit would remove or change $_gone existing line(s) of $CONFIG (expected $1); not writing it." "$(head -n 6 "$TMP/config.diff")"
  grep '^>' "$TMP/config.diff" | sed 's/^/            /'
  if [ "$DRY" = 1 ]; then would "back up $CONFIG, then write the lines above"; return 0; fi
  backup_config
  cmp -s "$CONFIG" "$ORIG" || fail "$CONFIG changed while this script was running; not writing it." "Nothing was changed by this script except the backup file. Re-run."
  install_config "$CUR" wmi-new || fail "cannot write $CONFIG; it was not changed (backup: $BACKUP)."
  cp "$CUR" "$ORIG" || fail "cannot update the working copy."
}
restore_config() { cmp -s "$CONFIG" "$ORIG" && install_config "$BACKUP" wmi-restore && cmp -s "$BACKUP" "$CONFIG"; }
verify_config() { # verify_config LABEL EXPECTED KEY...: read the value back through chezmoi; on a mismatch put the backup back
  _lab=$1; _exp=$2; shift 2
  _got=$(cdata "$@")
  if [ "$_got" != "$_exp" ]; then
    if restore_config; then fail "after the edit chezmoi reads $_lab as [$_got], not [$_exp]; $CONFIG was restored from $BACKUP (checked)."; fi
    fail "after the edit chezmoi reads $_lab as [$_got], not [$_exp], AND RESTORING $CONFIG FROM $BACKUP FAILED." "$CONFIG may be damaged. Put it back by hand: cp $BACKUP $CONFIG"
  fi
}
if [ -z "$EDITS" ]; then
  ok "profile and coordinator checkout are already set; nothing to add"
else
  info "to add:$EDITS"
  write_config 0
  if [ "$DRY" != 1 ]; then
    [ -z "$PROFILE" ] && verify_config profile "$WORK_PROFILE" profile
    [ -z "$DATA_REPO" ] && verify_config instances.coordinator.repo "$COORD_REAL" instances coordinator repo
    ok "added:$EDITS (read back through chezmoi)"
  fi
fi

# ---------------------------------------------------------------------------------------------------------------------------------------
step "3. Apply the instances files (the flag is not touched here)"
T_UNIT=$HOME/$UNIT_REL; T_SCRIPT=$HOME/$SCRIPT_REL; T_WRAPPER=$HOME/$WRAPPER_REL
if [ "$DRY" = 1 ]; then
  would "chezmoi apply -P --recursive=false  ~/$UNIT_REL  ~/$SCRIPT_REL   (and nothing else; the reconcile step runs only with --enable)"
else
  do_ "chezmoi apply (two files)"
  chezmoi apply --no-tty -P --recursive=false "$T_UNIT" "$T_SCRIPT" >"$TMP/apply.out" 2>&1; _rc=$?
  sed 's/^/            /' "$TMP/apply.out"
  [ "$_rc" = 0 ] || fail "chezmoi apply failed (exit $_rc)." "Nothing else was done. Read the lines above."
  [ -f "$T_UNIT" ] || fail "the inert unit $T_UNIT was not created." "Is the chezmoi profile really $WORK_PROFILE (the unit is ignored on other profiles)?"
  ok "inert unit in place: $T_UNIT"
fi

# ---------------------------------------------------------------------------------------------------------------------------------------
step "4. Compare the rendered unit with the live one"
LIVE_STATE=unknown
if command -v launchctl >/dev/null 2>&1; then
  launchctl print "gui/$(id -u)/$UNIT_NAME" >/dev/null 2>&1; _lr=$?
  case $_lr in 0) LIVE_STATE=loaded;; 113) LIVE_STATE='not loaded';; esac
fi
info "launchd: $UNIT_NAME is $LIVE_STATE (read-only check)"
RENDERED=$TMP/rendered.plist
render_unit() {
  if [ "$DRY" = 1 ]; then
    # Rendered against $CUR, a copy of the config with the lines this script would add. Older chezmoi has no --override-data, but every chezmoi has --config.
    chezmoi --config "$CUR" execute-template <"$TEMPLATE" >"$TMP/render.out" 2>"$TMP/err" || fail "cannot render the unit template." "$(head -n 3 "$TMP/err")"
    sed -n '/^<?xml/,/^<\/plist>/p' "$TMP/render.out" >"$RENDERED"   # hook output around the unit is dropped
    [ -s "$RENDERED" ] || fail "the rendered unit is empty: the template produced no plist."
  else
    cp "$T_UNIT" "$RENDERED" || fail "cannot copy the rendered unit $T_UNIT for the comparison."
  fi
}
compare_unit() { # sets CMP: none (nothing rendered), nolive, same, path (only the PATH differs; RP, LP set), other
  if [ -z "$RENDERED" ]; then CMP=none
  elif [ ! -f "$LIVE" ]; then CMP=nolive
  elif cmp -s "$RENDERED" "$LIVE"; then CMP=same
  else
    RP=$(plist_path "$RENDERED"); LP=$(plist_path "$LIVE")
    norm "$RENDERED" >"$TMP/r.norm"; norm "$LIVE" >"$TMP/l.norm"
    if cmp -s "$TMP/r.norm" "$TMP/l.norm" && [ -n "$RP" ] && [ -n "$LP" ]; then CMP=path; else CMP=other; fi
  fi
}
if [ "$DRY" = 1 ] && [ ! -f "$TEMPLATE" ]; then info "the unit template is not in the source yet; the comparison is done on a real run"; RENDERED=''
else render_unit; fi
compare_unit

# Only the start of PATH differs and extraPath is unset: take the prefix from the live unit (read-only) and ADD it to the config (never overwrite one).
if [ "$CMP" = path ] && [ -z "$EXTRA" ]; then
  case $LP in "$RP") _prefix='';; *":$RP") _prefix=${LP%":$RP"};; *) _prefix='';; esac
  if [ -n "$_prefix" ] && prefix_ok "$_prefix"; then
    info "only the start of PATH differs: the live unit has [$_prefix] in front of the default PATH."
    info "extraPath is derived from the live unit (read-only, never set by guess):"
    yaml_edit add "data instances coordinator extraPath" "\"$_prefix\""; _r=$?
    { [ "$_r" = 0 ] && [ "$EDIT_STATUS" = added ]; } || manual_edit "instances.coordinator.extraPath" 'data:' '  instances:' '    coordinator:' "      extraPath: \"$_prefix\""
    write_config 0
    if [ "$DRY" = 1 ]; then
      would "chezmoi apply ~/$UNIT_REL again, then compare again"
    else
      verify_config instances.coordinator.extraPath "$_prefix" instances coordinator extraPath
      ok "added instances.coordinator.extraPath: \"$_prefix\" (read back through chezmoi; backup: $BACKUP)"
      do_ "chezmoi apply (the unit file again)"
      chezmoi apply --no-tty -P --recursive=false "$T_UNIT" >"$TMP/apply1b.out" 2>&1; _rc=$?
      sed 's/^/            /' "$TMP/apply1b.out"
      [ "$_rc" = 0 ] || fail "chezmoi apply failed (exit $_rc) after extraPath was added to $CONFIG." "Backup of the config: $BACKUP. Read the lines above."
    fi
    EXTRA=$_prefix
    DERIVED_EXTRA=1
    render_unit; compare_unit
  fi
fi

case $CMP in
  none) ;;
  nolive) info "there is no live unit at $LIVE: nothing to compare (this Mac was not set up by hand, or the unit was removed)";;
  same) if [ "$DERIVED_EXTRA" = 1 ] && [ "$DRY" = 1 ]; then ok "the rendered unit would be identical to the live unit (with the extraPath above)"
        else ok "the rendered unit is identical to the live unit"; fi;;
  path)
    BASE=$RP; [ -n "$EXTRA" ] && BASE=${RP#"$EXTRA:"}
    if [ "$LP" = "$BASE" ]; then
      action "only the PATH differs: the live unit has no extra tool directories, but extraPath is set to [$EXTRA]." "Remove instances.coordinator.extraPath from $CONFIG and re-run. Nothing was changed for this."
    fi
    case $LP in
      *":$BASE") _prefix=${LP%":$BASE"}
        if [ -n "$EXTRA" ]; then
          action "only the start of PATH differs, and extraPath is already set to [$EXTRA], which this script never overwrites. The live unit has:" \
            "extraPath: \"$_prefix\"" "Change it by hand in $CONFIG under data: instances: coordinator:, then re-run. (live PATH: $LP)"
        fi
        action "only the start of PATH differs, but the live prefix [$_prefix] is not one this script will write into your config (absolute directories, plain characters only)." \
          "If it is right, add it by hand to $CONFIG under data: instances: coordinator:, then re-run:" "extraPath: \"$_prefix\"" "(live PATH: $LP)";;
      *) action "only PATH differs, and not by a prefix this script can express." "live PATH:     $LP" "rendered PATH: $RP" "Set extraPath so that extraPath:<default PATH> equals the live PATH, or ask for help.";;
    esac;;
  other)
    diff -u "$LIVE" "$RENDERED" | sed 's/^/            /'
    _lwd=$(plist_wd "$LIVE")
    action "the rendered unit differs from the live unit in more than PATH (diff above, live minus, rendered plus)." \
      "The live unit runs from [$_lwd]; the rendered one from [$(plist_wd "$RENDERED")]. If those differ, set instances.coordinator.repo to the live one." \
      "Nothing was changed for the live unit. Fix the cause and re-run.";;
esac

# ---------------------------------------------------------------------------------------------------------------------------------------
if [ "$ENABLE" != 1 ]; then
  step "Done (steps 1 to 4)."
  if [ "$ENABLED" = true ]; then say "   instances.coordinator.enabled is ALREADY true in your config (this script did not change it)."
  else say "   instances.coordinator.enabled is not set to true: the flag is still off."; fi
  say "   To adopt the running service (no restart): sh $SELF --enable${COORD_ARG:+ --coordinator $COORD_ARG}"
  exit 0
fi

step "5. Turn the flag on and apply"
STATE_CFG=$HOME/.local/share/coordinator-work/config.json
[ -f "$STATE_CFG" ] || fail "there is no $STATE_CFG: the work instance was not set up by hand here." \
  "Enabling would make dotfiles run the coordinator's setup script, which this script does not do. Do the coordinator's handoff first."
[ -f "$LIVE" ] || fail "there is no live unit at $LIVE: nothing to adopt." "This script only adopts a service that is already installed."
[ "$LIVE_STATE" = loaded ] || fail "launchd does not show $UNIT_NAME as loaded (state: $LIVE_STATE), so there is no running service to adopt." "Dotfiles would start it. Start it the way you did when you set it up, check it, and re-run."
MARKER=$HOME/.local/state/instances/coordinator-work.configuring
if [ -e "$MARKER" ] || [ -L "$MARKER" ]; then
  fail "the marker $MARKER exists: the next reconcile would run the coordinator's setup script (token, network, paid model check)." "If the work instance is set up and checked, remove the marker by hand (rm $MARKER) and re-run. This script does not remove it."
fi
ok "the work instance has its config, a live unit, a running service and no unfinished-setup marker"
if [ "$ENABLED" = true ]; then
  ok "instances.coordinator.enabled is already true"
else
  yaml_edit set "data instances coordinator enabled" true; _r=$?
  [ "$_r" = 0 ] || manual_edit "instances.coordinator.enabled" 'data:' '  instances:' '    coordinator:' '      enabled: true'
  if [ "$EDIT_STATUS" = added ]; then _removed=0; else _removed=1; fi
  write_config "$_removed"
  if [ "$DRY" != 1 ]; then verify_config instances.coordinator.enabled true instances coordinator enabled; ok "instances.coordinator.enabled is now true"; fi
fi
if [ "$DRY" = 1 ]; then
  would "chezmoi apply (the three targets, including the reconcile step): adopts the running service, no restart, and prints READY or NOT READY"
  step "Dry run finished: nothing was changed."
  exit 0
fi
do_ "chezmoi apply (three files, including the reconcile step)"
chezmoi apply --no-tty -P --recursive=false "$T_UNIT" "$T_SCRIPT" "$T_WRAPPER" >"$TMP/apply2.out" 2>&1; _rc=$?
sed 's/^/            /' "$TMP/apply2.out"
[ "$_rc" = 0 ] || fail "chezmoi apply failed (exit $_rc)." "The flag is on in $CONFIG; to turn it off set instances.coordinator.enabled: false there and apply."
RESULT=$(grep '^\[instances\] coordinator-work: ' "$TMP/apply2.out" | tail -n 1 | sed 's/^\[instances\] //')
[ -n "$RESULT" ] || fail "the reconcile step printed no coordinator-work result." "Read the apply output above."
case $RESULT in
  "coordinator-work: READY"*) ok "$RESULT"; step "Done. The work coordinator instance is managed by dotfiles; the flag is on."; exit 0;;
  *) printf '   [NOT READY] %s\n' "$RESULT" >&2
     printf '            The flag stays on and the next apply retries. To turn it off: set instances.coordinator.enabled: false in %s and apply.\n' "$CONFIG" >&2
     exit 5;;
esac
