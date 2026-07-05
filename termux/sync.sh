#!/usr/bin/env bash
# Push canonical Termux config from this repo to the connected Android device.
# Requires: adb, device with Termux installed and reachable.

set -euo pipefail

cd "$(dirname "$0")"

if ! adb get-state >/dev/null 2>&1; then
    echo "error: no adb device connected" >&2
    exit 1
fi

push_file() {
    local src="$1"
    local dest="$2"
    local tmp="/data/local/tmp/$(basename "$src").new"

    echo "→ pushing $src → $dest"
    adb push "$src" "$tmp" >/dev/null
    adb shell "run-as com.termux cp '$tmp' '$dest' && rm '$tmp'"
}

# Idempotently install the ntfy-harpoon-jump ControlMaster snippet into the phone
# ~/.ssh/config. Marker-guarded: a second run finds the sentinel and makes no
# change (Constitution IV). ControlPath parent (~/.ssh) is created if absent so
# the master socket can bind.
sync_controlmaster() {
    local src="ssh-controlmaster.config"
    local marker="# >>> ntfy-harpoon-jump controlmaster >>>"
    local tmp="/data/local/tmp/$src.new"

    echo "→ syncing ssh ControlMaster snippet → files/home/.ssh/config"
    adb push "$src" "$tmp" >/dev/null
    # Idempotence guard: the appended block is fenced by the sentinel marker, so a
    # re-run that finds the marker is a no-op (Constitution IV: no-op when already
    # applied by this script). This is the robust, unambiguous mechanism; parsing
    # arbitrary hand-written ssh stanzas from an adb run-as toybox shell is
    # intentionally out of scope (see follow-ups.md). ControlPath parent (~/.ssh)
    # is created if absent so the master socket can bind. A pre-existing MANUAL
    # `Host remote` ControlMaster block is the user's to reconcile (see README).
    adb shell "run-as com.termux sh -c '
        cfg=files/home/.ssh/config
        mkdir -p files/home/.ssh && chmod 700 files/home/.ssh
        touch \"\$cfg\" && chmod 600 \"\$cfg\"
        if grep -qF \"$marker\" \"\$cfg\"; then
            echo \"  (managed block present — no change)\"
        else
            printf \"\n\" >> \"\$cfg\"
            cat \"$tmp\" >> \"\$cfg\"
            echo \"  (appended ControlMaster block)\"
        fi
    '"
    # Remove the pushed tmp OUTSIDE run-as: /data/local/tmp/$tmp is owned by the
    # adb `shell` uid, so the Termux app uid inside run-as cannot delete it (the
    # cp/cat READ works, but rm would EACCES and — with set -euo pipefail — abort
    # the sync on every run, breaking Const IV). Mirror push_file's shell-uid rm.
    adb shell "rm -f '$tmp'"
}

push_file "termux.properties" "files/home/.termux/termux.properties"
push_file "font.ttf"          "files/home/.termux/font.ttf"
sync_controlmaster

echo "→ reloading Termux style"
adb shell 'am broadcast --user 0 -a com.termux.app.reload_style com.termux' \
    >/dev/null

echo "done."
