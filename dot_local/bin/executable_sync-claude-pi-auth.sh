#!/usr/bin/env bash
#
# sync-claude-pi-auth.sh
#
# Sync Claude Code's OAuth credentials (macOS Keychain item
# "Claude Code-credentials", falling back to ~/.claude/.credentials.json)
# into pi's auth file (~/.pi/agent/auth.json) so that:
#
#   - pi-sub-bar's anthropic provider (pi-sub-core/loadClaudeToken) finds
#     a non-stale token at ~/.pi/agent/auth.json -> .anthropic.access
#   - pi's web-search/web_fetch extension (~/.pi/agent/extensions/web-search)
#     finds a token with the richer shape it requires:
#         .anthropic.type    == "oauth"
#         .anthropic.access  == <accessToken>
#         .anthropic.expires == <expiresAt ms>
#
# Why this script exists:
#   Claude Code's credential storage on macOS has flip-flopped between the
#   Keychain item "Claude Code-credentials" and ~/.claude/.credentials.json
#   across releases (file-only around 2026-05; back to Keychain as of
#   2026-07-19, leaving the file as a stub with accessToken: "" and
#   expiresAt: 0). Tokens rotate ~every 8h, so a stale auth.json silently
#   breaks the sub-bar widget AND the web tools until re-synced. Reading
#   Keychain first with a file fallback survives either regime.
#
# Behavior:
#   - Reads accessToken + expiresAt from the Keychain item
#     "Claude Code-credentials" first; falls back to
#     ~/.claude/.credentials.json if the Keychain yields no usable token
#   - No-op (exit 0) if the destination already matches the source
#   - Writes atomically via tmp + mv; preserves a single .bak rolling backup
#   - --check  : only verify, do not write (exit 0 in-sync, exit 1 stale)
#   - --quiet  : suppress non-error output (for launchd / cron use)
#
# Exit codes:
#   0   success / already in sync
#   1   stale (with --check) or write failed
#   2   no usable credentials in Keychain or credentials file
#   3   prerequisite missing (jq)

set -euo pipefail

SOURCE_FILE="${HOME}/.claude/.credentials.json"
KEYCHAIN_SERVICE="Claude Code-credentials"
DEST="${HOME}/.pi/agent/auth.json"
BACKUP="${DEST}.bak"

CHECK_ONLY=0
QUIET=0
for arg in "$@"; do
  case "$arg" in
    --check) CHECK_ONLY=1 ;;
    --quiet|-q) QUIET=1 ;;
    -h|--help)
      sed -n '2,33p' "$0"
      exit 0
      ;;
    *)
      echo "unknown arg: $arg" >&2
      exit 64
      ;;
  esac
done

log() {
  [ "$QUIET" -eq 1 ] && return 0
  echo "$@"
}

err() {
  echo "$@" >&2
}

command -v jq >/dev/null 2>&1 || { err "jq not found in PATH"; exit 3; }

# Extract accessToken + expiresAt from a claudeAiOauth JSON blob on stdin.
# Prints "token<TAB>expires" if usable, nothing otherwise. A token is usable
# when non-empty and expiresAt is a positive number (stub files carry
# accessToken: "" / expiresAt: 0).
extract_creds() {
  jq -r '
    .claudeAiOauth as $c
    | if ($c.accessToken // "") != "" and (($c.expiresAt // 0) | tonumber? // 0) > 0
      then "\($c.accessToken)\t\($c.expiresAt)"
      else empty
      end
  ' 2>/dev/null || true
}

NEW_TOKEN=""
NEW_EXPIRES=""
SOURCE_DESC=""

# 1) macOS Keychain (current Claude Code storage)
KC_JSON=$(security find-generic-password -s "$KEYCHAIN_SERVICE" -w 2>/dev/null || true)
if [ -n "$KC_JSON" ]; then
  CREDS=$(printf '%s' "$KC_JSON" | extract_creds)
  if [ -n "$CREDS" ]; then
    NEW_TOKEN=${CREDS%%$'\t'*}
    NEW_EXPIRES=${CREDS##*$'\t'}
    SOURCE_DESC="keychain:${KEYCHAIN_SERVICE}"
  fi
fi

# 2) Fallback: credentials file (older Claude Code storage)
if [ -z "$NEW_TOKEN" ] && [ -r "$SOURCE_FILE" ]; then
  CREDS=$(extract_creds < "$SOURCE_FILE")
  if [ -n "$CREDS" ]; then
    NEW_TOKEN=${CREDS%%$'\t'*}
    NEW_EXPIRES=${CREDS##*$'\t'}
    SOURCE_DESC="$SOURCE_FILE"
  fi
fi

if [ -z "$NEW_TOKEN" ] || [ -z "$NEW_EXPIRES" ]; then
  err "no usable claudeAiOauth credentials in keychain '$KEYCHAIN_SERVICE' or $SOURCE_FILE"
  exit 2
fi



# Compare with current dest
CUR_TOKEN=""
CUR_EXPIRES=""
CUR_TYPE=""
if [ -r "$DEST" ]; then
  CUR_TOKEN=$(jq -r '.anthropic.access // empty' "$DEST" 2>/dev/null || true)
  CUR_EXPIRES=$(jq -r '.anthropic.expires // empty' "$DEST" 2>/dev/null || true)
  CUR_TYPE=$(jq -r '.anthropic.type // empty' "$DEST" 2>/dev/null || true)
fi

if [ "$CUR_TOKEN" = "$NEW_TOKEN" ] \
   && [ "$CUR_EXPIRES" = "$NEW_EXPIRES" ] \
   && [ "$CUR_TYPE" = "oauth" ]; then
  log "in sync via ${SOURCE_DESC} (token prefix ${NEW_TOKEN:0:20}..., expires $(date -r $((NEW_EXPIRES/1000)) '+%Y-%m-%d %H:%M:%S'))"
  exit 0
fi

if [ "$CHECK_ONLY" -eq 1 ]; then
  err "stale: pi auth.json does not match Claude Code credentials"
  exit 1
fi

# Ensure dest dir + parent file exist
mkdir -p "$(dirname "$DEST")"
if [ ! -f "$DEST" ]; then
  echo '{}' > "$DEST"
fi

# Backup current
cp "$DEST" "$BACKUP"

# Atomic update
TMP=$(mktemp "${DEST}.XXXXXX")
trap 'rm -f "$TMP"' EXIT
jq --arg t "$NEW_TOKEN" --argjson e "$NEW_EXPIRES" \
   '.anthropic = ((.anthropic // {}) + {access: $t, type: "oauth", expires: $e})' \
   "$DEST" > "$TMP"

# Sanity: ensure tmp is valid JSON with expected shape
jq -e '.anthropic.access and .anthropic.type == "oauth" and .anthropic.expires' "$TMP" >/dev/null || {
  err "post-write validation failed; leaving $DEST untouched"
  exit 1
}

mv "$TMP" "$DEST"
trap - EXIT

log "synced from ${SOURCE_DESC} (token prefix ${NEW_TOKEN:0:20}..., expires $(date -r $((NEW_EXPIRES/1000)) '+%Y-%m-%d %H:%M:%S'))"
log "backup: $BACKUP"
