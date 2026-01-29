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

# Check if op is available
if ! command -v op >/dev/null 2>&1; then
  echo "[update_claude_settings] ERROR: 1Password CLI (op) is required but not installed"
  exit 1
fi

# Get auth token from 1Password
echo "[update_claude_settings] INFO: Retrieving ANTHROPIC_AUTH_TOKEN from 1Password..."
ANTHROPIC_AUTH_TOKEN=$(op read 'op://personal/z.ai - key 1/credential' --no-newline 2>&1)
if [ $? -ne 0 ]; then
  echo "[update_claude_settings] ERROR: Failed to retrieve auth token from 1Password: $ANTHROPIC_AUTH_TOKEN"
  exit 1
fi

# Update settings.json using jq
jq --arg auth_token "$ANTHROPIC_AUTH_TOKEN" '
  .env.CLAUDE_CODE_ENABLE_TELEMETRY = "0" |
  .env.ANTHROPIC_BASE_URL = "https://api.z.ai/api/anthropic" |
  .env.API_TIMEOUT_MS = "3000000" |
  .env.ANTHROPIC_AUTH_TOKEN = $auth_token |
  .env.ANTHROPIC_API_KEY = ""
' "$SETTINGS_FILE" >"$SETTINGS_FILE.tmp" && mv "$SETTINGS_FILE.tmp" "$SETTINGS_FILE"

if [ $? -eq 0 ]; then
  echo "[update_claude_settings] SUCCESS: Updated $SETTINGS_FILE"
else
  echo "[update_claude_settings] ERROR: Failed to update settings file"
  rm -f "$SETTINGS_FILE.tmp"
  exit 1
fi
