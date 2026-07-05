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
#   NTFY_SERVER      required  base URL of the (self-hosted) ntfy server
#   NTFY_TOPIC       required  topic to publish to
#   NTFY_TOKEN_FILE  optional  path to a file holding a bearer token
#   NTFY_TOKEN       optional  bearer token value (prefer NTFY_TOKEN_FILE)
#
# Usage: ntfy-zellij-notify.sh <message> [title]
#
# Jump key: the STABLE pane id from $ZELLIJ_PANE_ID (form `terminal_N`, equal to
# harpoon's PaneInfo.id). Slot numbers are intentionally NOT used as the jump key
# (they are reassignable between send and tap); the slot, when resolvable, rides
# along only as a human-facing display hint.

set -euo pipefail

die() {
	printf 'ntfy-zellij-notify: %s\n' "$1" >&2
	exit 1
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
[ -n "$pane_id" ] && headers+=(-H "X-Jump-Pane: $pane_id")
[ -n "$session" ] && headers+=(-H "X-Zellij-Session: $session")
[ -n "$slot" ] && headers+=(-H "X-Harpoon-Slot: $slot")
[ -n "$token" ] && headers+=(-H "Authorization: Bearer $token")

curl -fsS "${headers[@]}" -d "$msg" "${NTFY_SERVER%/}/$NTFY_TOPIC" >/dev/null
