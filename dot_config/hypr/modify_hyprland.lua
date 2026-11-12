#!/bin/sh
#
# chezmoi modify_ script for ~/.config/hypr/hyprland.lua (Omarchy, personal Linux).
#
# Omarchy's default rule /usr/share/omarchy/default/hypr/apps/1password.lua sets no_screen_share on
# 1Password windows, so they show as a black box in screen shares and RustDesk. Michael, 2026-11-12:
# "off for good please". hyprland.lua loads after the defaults, so a later rule with
# no_screen_share = false turns it off for every 1Password window, new ones included.
#
# Omarchy owns the rest of hyprland.lua, so this script passes it through and only keeps one
# marked block at the end. Idempotent: an existing block is replaced, never duplicated. If the
# file does not exist yet (stdin is empty) nothing is written.

set -eu

BEGIN='-- BEGIN dotfiles: 1Password in screen shares'
END='-- END dotfiles: 1Password in screen shares'

existing=$(cat; printf x)
existing=${existing%x}

[ -n "$existing" ] || exit 0

# Pass the file through without any earlier copy of our block.
printf '%s' "$existing" | awk -v b="$BEGIN" -v e="$END" '
	$0 == b { skip = 1; next }
	skip && $0 == e { skip = 0; next }
	!skip
'

printf '%s\n' "$BEGIN" \
	'o.window("^(1[pP]assword|com\\.onepassword\\.OnePassword)$", { no_screen_share = false })' \
	"$END"
