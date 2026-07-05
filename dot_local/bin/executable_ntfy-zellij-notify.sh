#!/usr/bin/env bash
# ntfy-zellij-notify — publish an ntfy notification stamped with the caller's
# zellij location, so a phone tap can jump the live remote zellij session to the
# exact pane via harpoon `jump_pane`.
#
# Part of the cross-repo `ntfy-harpoon-jump` feature (chezmoi slice). Deployed to
# the homelab remote's ~/.local/bin/ via `chezmoi apply` (Constitution I). The
# alerting process on the remote calls this wrapper.
#
# Config comes from the ENVIRONMENT only — no literal secrets in this repo
# (Constitution III):
#   NTFY_SERVER       required  base URL of the (self-hosted) ntfy server
#   NTFY_TOPIC        required  topic to publish to
#   JUMP_SSH_HOST     required  when inside a zellij pane: the ssh host ALIAS the
#                              phone side-channels to on tap (`ssh $JUMP_SSH_HOST
#                              'zellij pipe --name jump_pane <pane>'`). Reference
#                              storage location only (a ~/.ssh/config alias); no
#                              secrets here (Constitution III).
#   NTFY_TOKEN_FILE   optional  path to a file holding a bearer token
#   NTFY_TOKEN        optional  bearer token value (prefer NTFY_TOKEN_FILE)
#   JUMP_DEEPLINK_BASE optional deep-link scheme+path the phone registers; MUST
#                              match the termux-app fork's registered handler.
#                              Default: termux-harpoon-jump://jump
#
# Usage: ntfy-zellij-notify.sh <message> [title]
#
# Jump key: the STABLE pane id from $ZELLIJ_PANE_ID (form `terminal_N`, equal to
# harpoon's PaneInfo.id). Slot numbers are intentionally NOT used as the jump key
# (they are reassignable between send and tap); the slot, when resolvable, rides
# along only as a human-facing display hint. The pane id (plus host + session) is
# carried on the ntfy `Click` deep-link URL — tapping the notification opens the
# termux-app fork's jump handler. Custom X-* headers are NOT propagated by ntfy to
# the client, so the jump payload MUST ride the Click URL, never a header.

set -euo pipefail

die() {
	printf 'ntfy-zellij-notify: %s\n' "$1" >&2
	exit 1
}

# Minimal RFC-3986 percent-encoder for deep-link query values.
urlencode() {
	local s="$1" i c out=""
	for ((i = 0; i < ${#s}; i++)); do
		c="${s:i:1}"
		case "$c" in
		[a-zA-Z0-9._~-]) out+="$c" ;;
		*) printf -v c '%%%02X' "'$c"; out+="$c" ;;
		esac
	done
	printf '%s' "$out"
}

msg="${1:-}"
[ -n "$msg" ] || die "missing required argument: <message>"
title="${2:-zellij alert}"

# --- required config (fail closed, naming the missing value) -----------------
: "${NTFY_SERVER:?ntfy-zellij-notify: NTFY_SERVER is not set}"
: "${NTFY_TOPIC:?ntfy-zellij-notify: NTFY_TOPIC is not set}"

# --- optional bearer token (file preferred over inline) ----------------------
token=""
if [ -n "${NTFY_TOKEN_FILE:-}" ]; then
	[ -r "$NTFY_TOKEN_FILE" ] || die "NTFY_TOKEN_FILE not readable: $NTFY_TOKEN_FILE"
	token="$(cat "$NTFY_TOKEN_FILE")"
elif [ -n "${NTFY_TOKEN:-}" ]; then
	token="$NTFY_TOKEN"
fi

# --- zellij location ---------------------------------------------------------
# $ZELLIJ_PANE_ID is exported in every zellij pane (form `terminal_N`); absent
# when the caller is not inside a zellij pane — degrade to a keyless notification.
pane_id="${ZELLIJ_PANE_ID:-}"
session="${ZELLIJ_SESSION_NAME:-}"

# Best-effort harpoon slot display hint. Never let a failed/absent lookup abort
# delivery: harpoon may be unloaded, or the pane may not be harpooned.
slot=""
if [ -n "$pane_id" ] && command -v zellij >/dev/null 2>&1; then
	slot="$(zellij pipe --name slot_for_pane \
		--plugin "file:$HOME/.config/zellij/plugins/harpoon.wasm" \
		"$pane_id" 2>/dev/null || true)"
fi

# --- assemble + publish ------------------------------------------------------
headers=(-H "Title: $title")
[ -n "$token" ] && headers+=(-H "Authorization: Bearer $token")

# Build the phone tap target. Inside a zellij pane, emit an ntfy `Click` deep
# link carrying the STABLE pane id (+ session + slot hint + host) so tapping the
# notification drives the termux-app fork's jump handler, which side-channels
# `ssh $JUMP_SSH_HOST 'zellij pipe --name jump_pane <pane_id>'` over the live
# ControlMaster connection. Outside zellij (no pane id) the notification is
# delivered keyless — no Click, no jump.
if [ -n "$pane_id" ]; then
	: "${JUMP_SSH_HOST:?ntfy-zellij-notify: JUMP_SSH_HOST is not set (required to build the jump tap target)}"
	click="${JUMP_DEEPLINK_BASE:-termux-harpoon-jump://jump}"
	click+="?host=$(urlencode "$JUMP_SSH_HOST")&pane=$(urlencode "$pane_id")"
	[ -n "$session" ] && click+="&session=$(urlencode "$session")"
	[ -n "$slot" ] && click+="&slot=$(urlencode "$slot")"
	headers+=(-H "Click: $click")
fi

# --data-raw (not -d): a message beginning with `@` would otherwise be read by
# curl as a filename.
curl -fsS "${headers[@]}" --data-raw "$msg" "${NTFY_SERVER%/}/$NTFY_TOPIC" >/dev/null
