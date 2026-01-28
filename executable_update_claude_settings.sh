#!/bin/sh

# Script to update ~/.claude/settings.json
# - Disables telemetry
# - Sets ANTHROPIC_BASE_URL, API_TIMEOUT_MS, and ANTHROPIC_AUTH_TOKEN from 1Password

SETTINGS_FILE="$HOME/.claude/settings.json"

# Check if settings file exists
if [ ! -f "$SETTINGS_FILE" ]; then
  echo "[update_claude_settings] ERROR: $SETTINGS_FILE not found"
  exit 1
fi

# Check if jq is available
if ! command -v jq >/dev/null 2>&1; then
  echo "[update_claude_settings] ERROR: jq is required but not installed"
  exit 1
fi

# Update settings.json using jq
jq --arg apiKeyHelperPath "$HOME/.claude/z-ai-api-key-helper.sh" '
  .env.CLAUDE_CODE_ENABLE_TELEMETRY = "0" |
  .env.ANTHROPIC_BASE_URL = "https://api.z.ai/api/anthropic" |
  .env.API_TIMEOUT_MS = "3000000" |
  .env.CLAUDE_CODE_API_KEY_HELPER_TTL_MS  = "999999999999" |
  .apiKeyHelper = $apiKeyHelperPath 
' "$SETTINGS_FILE" >"$SETTINGS_FILE.tmp" && mv "$SETTINGS_FILE.tmp" "$SETTINGS_FILE"

if [ $? -eq 0 ]; then
  echo "[update_claude_settings] SUCCESS: Updated $SETTINGS_FILE"
else
  echo "[update_claude_settings] ERROR: Failed to update settings file"
  rm -f "$SETTINGS_FILE.tmp"
  exit 1
fi
