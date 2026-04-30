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

push_file "termux.properties" "files/home/.termux/termux.properties"
push_file "font.ttf"          "files/home/.termux/font.ttf"

echo "→ reloading Termux style"
adb shell 'am broadcast --user 0 -a com.termux.app.reload_style com.termux' \
    >/dev/null

echo "done."
