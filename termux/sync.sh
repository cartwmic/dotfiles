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
    # Idempotence guard (toybox grep+sed only — no awk on the run-as PATH):
    #  1. managed sentinel present → our prior run applied it → skip.
    #  2. the `Host …remote` stanza ITSELF already carries a ControlMaster
    #     directive → skip to satisfy the spec AC "SHALL NOT append a duplicate
    #     block"; warn so the user can merge by hand. The sed range extracts only
    #     the remote stanza (Host…remote line up to the next Host line), so a
    #     ControlMaster in an UNRELATED stanza no longer false-skips the append.
    adb shell "run-as com.termux sh -c '
        cfg=files/home/.ssh/config
        mkdir -p files/home/.ssh && chmod 700 files/home/.ssh
        touch \"\$cfg\" && chmod 600 \"\$cfg\"
        if grep -qF \"$marker\" \"\$cfg\"; then
            echo \"  (managed block present — no change)\"
        elif sed -n \"/^[[:space:]]*[Hh]ost[[:space:]].*remote/,/^[[:space:]]*[Hh]ost[[:space:]]/p\" \"\$cfg\" | grep -qi controlmaster; then
            echo \"  (existing Host remote ControlMaster block — skipping to avoid a duplicate; merge manually if desired)\"
        else
            printf \"\n\" >> \"\$cfg\"
            cat \"$tmp\" >> \"\$cfg\"
            echo \"  (appended ControlMaster block)\"
        fi
        rm -f \"$tmp\"
    '"
}

push_file "termux.properties" "files/home/.termux/termux.properties"
push_file "font.ttf"          "files/home/.termux/font.ttf"
sync_controlmaster

echo "→ reloading Termux style"
adb shell 'am broadcast --user 0 -a com.termux.app.reload_style com.termux' \
    >/dev/null

echo "done."
