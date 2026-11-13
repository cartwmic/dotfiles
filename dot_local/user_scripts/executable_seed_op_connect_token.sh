#!/bin/sh
#
# seed_op_connect_token.sh
#
# Writes ~/.config/agent-harness/op-connect-token (mode 0600) so agents' op reads go to the homelab 1Password Connect
# server (dot_pi/private_agent/bin/executable_op). The token is the Connect access token in the item
# 'homelab-connect Access Token: agents' (op://developer/y3x5tr3p2calmede76mmkfdele/credential), read with the
# service account. The token is never printed.
#
# Exit 0 when the file already has a value (no 1Password read, so an apply costs no service-account request). To
# replace a rotated token, delete the file and run this again.
# Exit 0 with a WARN when there is no service-account token or no op: an apply is never blocked on this.
# Exit 1 when op is there and the read gives no value.
#
# Override for tests: OP_CONNECT_TOKEN_FILE names the file (the shim reads the same file).

set -eu

SCRIPT_NAME="$(basename "$0")"
LOG_PREFIX="[${SCRIPT_NAME}]"
TOKEN_FILE="${OP_CONNECT_TOKEN_FILE:-$HOME/.config/agent-harness/op-connect-token}"
SA_TOKEN_FILE="$HOME/.config/agent-harness/op-service-token"
CONNECT_TOKEN_REF='op://developer/y3x5tr3p2calmede76mmkfdele/credential'

log() { printf '%s %s\n' "$LOG_PREFIX" "$1" >&2; }
warn() { printf '%s WARN: %s\n' "$LOG_PREFIX" "$1" >&2; }

if [ -s "$TOKEN_FILE" ]; then
  exit 0
fi

sa_token="${OP_SERVICE_ACCOUNT_TOKEN:-}"
if [ -z "$sa_token" ] && [ -r "$SA_TOKEN_FILE" ]; then
  sa_token="$(tr -d '\n\r' < "$SA_TOKEN_FILE")"
fi
if [ -z "$sa_token" ]; then
  warn "no service-account token (OP_SERVICE_ACCOUNT_TOKEN or $SA_TOKEN_FILE); Connect token not seeded"
  exit 0
fi
if ! command -v op >/dev/null 2>&1; then
  warn "1Password CLI (op) not found; Connect token not seeded"
  exit 0
fi

work=""
tmp=""
trap 'rm -rf "$work"; if [ -n "$tmp" ]; then rm -f "$tmp"; fi' EXIT
work="$(mktemp -d "${TMPDIR:-/tmp}/seed-op-connect.XXXXXX")"

# The read runs under an empty HOME, as the shim does for the service account, so the desktop app cannot answer it, and
# with no Connect variables, so it cannot go to Connect.
if ! value="$(
  unset OP_CONNECT_TOKEN OP_CONNECT_HOST
  HOME="$work" OP_SERVICE_ACCOUNT_TOKEN="$sa_token" op read "$CONNECT_TOKEN_REF" 2>"$work/err"
)"; then
  warn "op read failed for the Connect token item: $(head -n 1 "$work/err" 2>/dev/null || true)"
  exit 1
fi
if [ -z "$value" ]; then
  warn "op read gave no value for the Connect token item"
  exit 1
fi

umask 077
dir="$(dirname "$TOKEN_FILE")"
mkdir -p "$dir"
tmp="$(mktemp "$dir/.op-connect-token.XXXXXX")"
printf '%s\n' "$value" > "$tmp"
chmod 600 "$tmp"
mv -f "$tmp" "$TOKEN_FILE"
log "wrote $TOKEN_FILE (mode 0600)"
