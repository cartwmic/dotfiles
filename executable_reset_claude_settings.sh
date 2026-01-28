#!/bin/sh

# Script to reset ~/.claude/settings.json to defaults
# - Re-enables telemetry
# - Removes ANTHROPIC_BASE_URL, API_TIMEOUT_MS, and ANTHROPIC_AUTH_TOKEN from env

SETTINGS_FILE="$HOME/.claude/settings.json"

# Check if settings file exists
if [ ! -f "$SETTINGS_FILE" ]; then
  echo "[reset_claude_settings] ERROR: $SETTINGS_FILE not found"
  exit 1
fi

# Check if jq is available
if ! command -v jq >/dev/null 2>&1; then
  echo "[reset_claude_settings] ERROR: jq is required but not installed"
  exit 1
fi

# Update settings.json using jq
jq '
  .env.CLAUDE_CODE_ENABLE_TELEMETRY = "1" |
  del(.env.ANTHROPIC_BASE_URL) |
  del(.env.API_TIMEOUT_MS) |
  del(.apiKeyHelper)
' "$SETTINGS_FILE" >"$SETTINGS_FILE.tmp" && mv "$SETTINGS_FILE.tmp" "$SETTINGS_FILE"

if [ $? -eq 0 ]; then
  echo "[reset_claude_settings] SUCCESS: Reset $SETTINGS_FILE to defaults"
else
  echo "[reset_claude_settings] ERROR: Failed to update settings file"
  rm -f "$SETTINGS_FILE.tmp"
  exit 1
fi
