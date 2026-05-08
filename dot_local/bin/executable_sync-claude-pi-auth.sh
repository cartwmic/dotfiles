#!/usr/bin/env bash
#
# sync-claude-pi-auth.sh
#
# Sync Claude Code's OAuth credentials (~/.claude/.credentials.json) into
# pi's auth file (~/.pi/agent/auth.json) so that:
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
#   Recent Claude Code on macOS writes only ~/.claude/.credentials.json and
#   no longer seeds the macOS Keychain item "Claude Code-credentials" that
#   pi-sub-core's third fallback expects. Tokens rotate ~every 8h, so the
#   stale auth.json silently breaks the sub-bar widget AND the web tools
#   until manually re-synced. See memory hash 1faf7f80... (2026-05-06).
#
# Behavior:
#   - Reads accessToken + expiresAt from ~/.claude/.credentials.json
#   - No-op (exit 0) if the destination already matches the source
#   - Writes atomically via tmp + mv; preserves a single .bak rolling backup
#   - --check  : only verify, do not write (exit 0 in-sync, exit 1 stale)
#   - --quiet  : suppress non-error output (for launchd / cron use)
#
# Exit codes:
#   0   success / already in sync
#   1   stale (with --check) or write failed
#   2   source credentials file missing or unreadable
#   3   prerequisite missing (jq)

set -euo pipefail

SOURCE="${HOME}/.claude/.credentials.json"
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

if [ ! -r "$SOURCE" ]; then
  err "source not readable: $SOURCE"
  exit 2
fi

NEW_TOKEN=$(jq -r '.claudeAiOauth.accessToken // empty' "$SOURCE")
NEW_EXPIRES=$(jq -r '.claudeAiOauth.expiresAt // empty' "$SOURCE")

if [ -z "$NEW_TOKEN" ] || [ -z "$NEW_EXPIRES" ]; then
  err "source missing claudeAiOauth.accessToken or .expiresAt"
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
  log "in sync (token prefix ${NEW_TOKEN:0:20}..., expires $(date -r $((NEW_EXPIRES/1000)) '+%Y-%m-%d %H:%M:%S'))"
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

log "synced (token prefix ${NEW_TOKEN:0:20}..., expires $(date -r $((NEW_EXPIRES/1000)) '+%Y-%m-%d %H:%M:%S'))"
log "backup: $BACKUP"
