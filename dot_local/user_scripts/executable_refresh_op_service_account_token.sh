#!/bin/sh
#
# refresh_op_service_account_token.sh
#
# Fetch the 1Password service-account token from 1Password using the regular
# `op` CLI (which will prompt for biometric / desktop-app auth — this is the
# one place we accept a prompt) and write it to the file expected by:
#   - private_dot_zshrc (sources it into $OP_SERVICE_ACCOUNT_TOKEN at shell start)
#   - executable_apply_harness_config.sh (resolve_secret reads the file directly
#     when $OP_SERVICE_ACCOUNT_TOKEN isn't already set)
#
# Run this once per machine after creating/rotating the service account.
# Override the source location with the env vars below, e.g.:
#   AGENT_HARNESS_OP_VAULT=personal \
#   AGENT_HARNESS_OP_ITEM='Service Account Auth Token: dotfiles' \
#   AGENT_HARNESS_OP_FIELD=credential \
#     refresh_op_service_account_token.sh
#
# Uses `op item get` rather than `op read` because op:// secret references
# disallow colons (and several other characters) in item names, while
# `op item get --fields` handles arbitrary item names cleanly.

set -eu

SCRIPT_NAME="refresh_op_service_account_token"
TOKEN_FILE="${AGENT_HARNESS_OP_TOKEN_FILE:-$HOME/.config/agent-harness/op-service-token}"
OP_VAULT="${AGENT_HARNESS_OP_VAULT:-personal}"
OP_ITEM="${AGENT_HARNESS_OP_ITEM:-Service Account Auth Token: dotfiles}"
OP_FIELD="${AGENT_HARNESS_OP_FIELD:-credential}"

log() {
  echo "[$SCRIPT_NAME] $1"
}

log_error() {
  echo "[$SCRIPT_NAME] ERROR: $1" >&2
}

if ! command -v op >/dev/null 2>&1; then
  log_error "1Password CLI (op) not found in PATH"
  exit 1
fi

# Don't accidentally use a stale SA token to fetch the SA token. Force the
# regular interactive path so this script can prompt for biometrics.
unset OP_SERVICE_ACCOUNT_TOKEN

log "Fetching service-account token from 1Password: $OP_VAULT / $OP_ITEM / $OP_FIELD"
log "(biometric / desktop-app auth prompt expected)"

# Pipe through python to extract the field value from JSON. Avoids both
# shell quoting issues and accidental whitespace/newline mangling.
if ! op_json=$(op item get "$OP_ITEM" --vault "$OP_VAULT" --fields "$OP_FIELD" --reveal --format json 2>&1); then
  log_error "op item get failed: $op_json"
  log_error "Verify item exists at vault='$OP_VAULT' item='$OP_ITEM' field='$OP_FIELD'"
  log_error "Override with: AGENT_HARNESS_OP_VAULT, AGENT_HARNESS_OP_ITEM, AGENT_HARNESS_OP_FIELD"
  exit 1
fi

if ! token=$(printf '%s' "$op_json" | python3 -c 'import json,sys; sys.stdout.write(json.load(sys.stdin)["value"])' 2>/dev/null); then
  log_error "Failed to extract value from op response (item missing the '$OP_FIELD' field?)"
  exit 1
fi

if [ -z "$token" ]; then
  log_error "op returned an empty value for $OP_VAULT / $OP_ITEM / $OP_FIELD"
  exit 1
fi

case "$token" in
  ops_*) ;;
  *)
    log_error "Fetched value does not look like a service-account token (expected 'ops_...' prefix)"
    log_error "Check the field name in $TOKEN_REF"
    exit 1
    ;;
esac

token_dir=$(dirname "$TOKEN_FILE")
mkdir -p "$token_dir"
chmod 700 "$token_dir"

# Atomic write: stage to a sibling temp file, chmod, then rename.
tmp_file="$TOKEN_FILE.tmp.$$"
trap 'rm -f "$tmp_file"' EXIT
umask 077
printf '%s' "$token" > "$tmp_file"
chmod 600 "$tmp_file"
mv "$tmp_file" "$TOKEN_FILE"
trap - EXIT

log "Wrote token to $TOKEN_FILE (mode 0600)"

# Verification: use the new token to call op whoami via service-account auth.
if OP_SERVICE_ACCOUNT_TOKEN="$token" op whoami >/dev/null 2>&1; then
  log "Verified: token authenticates successfully via service-account flow"
else
  log_error "Token written but 'op whoami' under service-account auth failed"
  log_error "The token may be expired or revoked; create a new one in 1Password"
  exit 1
fi

log "Done. Open a new shell (or 'source ~/.zshrc') to pick up \$OP_SERVICE_ACCOUNT_TOKEN."
